import json
import re
import urllib.request
import urllib.error
from typing import Dict, Any, List, Tuple

class LLMAgent:
    """Interface genérica para os agentes de LLM."""
    def generate_response(self, prompt: str) -> str:
        raise NotImplementedError("Subclasses devem implementar este método.")


_STOP_WORDS = {
    "for", "of", "the", "a", "o", "do", "da", "de", "por", "para", "em", "no", "na",
    "on", "in", "by", "to", "with", "at", "as", "an",
    "recipe", "receita", "recipes", "receitas",
    "my", "meu", "minha", "this", "este", "essa", "esse",
}


def _extract_name(rest: str) -> str:
    if not rest:
        return "RECIPE"
    for token in rest.split():
        clean = token.strip(".,;:?!\"'`()[]{}")
        if clean and clean.lower() not in _STOP_WORDS:
            return clean
    return "RECIPE"


class DeterministicLLMMock(LLMAgent):
    """Mock local determinístico para fallback offline. Suporta PT-BR e EN.

    Cada padrão é testado em ordem; o primeiro que casa vence. Padrões mais
    específicos (impact, deps) ficam antes dos mais genéricos (search, info)
    para evitar classificação errada em frases compostas como "what depends
    on openssl" (impact, não deps).
    """

    _PATTERNS: List[Tuple[str, str, str, str]] = [
        (r"\b(impact|reverse[\s-]?deps?|quem\s+depende|what\s+depends|afetad[oa])\b\s*(?P<rest>.+)?",
         "recipe", "recipe impact {name}", "Mostra quem depende de uma receita (impacto reverso)."),
        (r"\b(deps?(?=\b|_)|depend[eê]ncias?|depende\s+de|tree\s+of|graph\s+of)\b\s*(?P<rest>.+)?",
         "recipe", "recipe deps {name}", "Exibe a árvore de dependências de uma receita."),
        (r"\b(search|find|buscar?|procurar?|listar?|locate)\b\s*(?P<rest>.+)?",
         "recipe", "recipe search {name}", "Procura uma receita indexada por nome."),
        (r"\b(fix|corrigir|consertar|repair|autofix|auto[\s-]?fix|rebuild|recompil\w*)\b",
         "fix", "fix build.log", "Aplica correção automática com sandbox + rollback transacional."),
        (r"\b(diagnose|diagnost\w*|analisar?\s+log|build\s+(?:error|failure|fail|erro|falha)|nothing\s+provides)\b",
         "diagnose", "diagnose build.log", "Analisa um log de build do Bitbake em busca de erros."),
        (r"\b(cve|securit\w+|seguran[çc]a|vulnerab\w*)\b",
         "security", "security", "Varre o workspace em busca de CVEs (modo offline por padrão, use --online para NVD)."),
        (r"\b(dts|device[\s-]?tree|hardware|pinctrl|board)\b",
         "hardware", "hardware board.dts", "Analisa um Device Tree com dtc + dt-validate."),
        (r"\b(dmesg|kernel[\s-]?log|panic|oops|soft[\s-]?lockup|out[\s-]?of[\s-]?memory|oom|runtime)\b",
         "runtime", "runtime dmesg.log", "Analisa logs de runtime do target (kernel oops, OOM, panic)."),
        (r"\b(explain|explicar?|describe|descrever?|o\s+que\s+[eé]|what\s+is|tell\s+me\s+about)\b\s*(?P<rest>.+)?",
         "explain", "explain {name}", "Explica o que uma receita faz."),
        (r"\b(append[\s-]?conf|adicionar\s+ao\s+local\.conf|add\s+to\s+local\.conf)\b",
         "action", 'action append-conf "VAR = value"', "Adiciona uma linha ao conf/local.conf."),
        (r"\b(add[\s-]?layer|adicionar[\s-]?layer|nova[\s-]?layer)\b",
         "action", "action add-layer /path/to/layer", "Adiciona uma layer ao bblayers.conf."),
        (r"\b(patch[\s-]?recipe|modify[\s-]?recipe|modificar[\s-]?receita)\b",
         "action", 'action patch-recipe RECIPE VAR "value"', "Acrescenta variável em .bbappend de uma receita."),
        (r"\b(info|workspace|status|detect|version|about)\b",
         "info", "info", "Mostra informações do workspace Yocto/Buildroot detectado."),
    ]

    def generate_response(self, prompt: str) -> str:
        prompt_lower = prompt.lower()
        for pattern, intent, command_tpl, explanation in self._PATTERNS:
            m = re.search(pattern, prompt_lower)
            if m:
                name = _extract_name(m.groupdict().get("rest") or "")
                cmd = command_tpl.format(name=name)
                return json.dumps({
                    "intent": intent,
                    "command": cmd,
                    "explanation": explanation,
                })
        return json.dumps({
            "intent": "unknown",
            "command": None,
            "explanation": (
                "Não reconheci a intenção. Comandos disponíveis: info, diagnose LOG, "
                "recipe (search/deps/impact NAME), fix LOG, security, hardware DTS, "
                "runtime DMESG, explain RECIPE, action (append-conf/add-layer/patch-recipe)."
            ),
        })

class OllamaAgent(LLMAgent):
    """Cliente nativo do Ollama Local."""
    def __init__(self, model: str = "qwen2.5:7b", base_url: str = "http://localhost:11434"):
        self.model = model
        self.base_url = base_url

    def generate_response(self, prompt: str) -> str:
        url = f"{self.base_url}/api/generate"
        system_prompt = (
            "You are Titan Engineering Router, a deterministic assistant for Yocto and Buildroot.\n"
            "Your ONLY job is to translate the user query into a structured JSON command for the Titan CLI.\n"
            "Respond ONLY with a raw single-line JSON object. Do not output markdown, backticks, or explanatory text.\n"
            "JSON Schema:\n"
            "{\"intent\": \"recipe|diagnose|action|info\", \"command\": \"<cli command>\", \"explanation\": \"<short reason>\"}\n"
            "Examples:\n"
            "- 'see graph for curl' -> {\"intent\": \"recipe\", \"command\": \"recipe deps curl\", \"explanation\": \"Show dependencies of curl\"}"
        )
        payload = {
            "model": self.model,
            "prompt": f"{system_prompt}\n\nUser query: {prompt}\nJSON Output:",
            "stream": False,
            "options": {"temperature": 0.0}
        }
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode('utf-8'),
                headers={'Content-Type': 'application/json'},
                method='POST'
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                res_data = json.loads(response.read().decode('utf-8'))
                return res_data.get("response", "").strip()
        except Exception as e:
            raise RuntimeError(f"Falha ao contatar Ollama local: {e}")

class OpenRouterAgent(LLMAgent):
    """Cliente nativo do OpenRouter usando a API compatível com OpenAI."""
    def __init__(self, api_key: str, model: str = "meta-llama/llama-3-8b-instruct:free", base_url: str = "https://openrouter.ai/api/v1"):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url

    def generate_response(self, prompt: str) -> str:
        url = f"{self.base_url}/chat/completions"
        system_prompt = (
            "You are Titan Engineering Router, a deterministic assistant for Yocto and Buildroot.\n"
            "Your ONLY job is to translate the user query into a structured JSON command for the Titan CLI.\n"
            "Respond ONLY with a raw single-line JSON object. Do not output markdown, backticks, or explanatory text.\n"
            "JSON Schema:\n"
            "{\"intent\": \"recipe|diagnose|action|info\", \"command\": \"<cli command>\", \"explanation\": \"<short reason>\"}"
        )
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.0
        }
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.api_key}',
            'HTTP-Referer': 'https://github.com/titan-framework/titan',
            'X-Title': 'Titan Framework'
        }
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode('utf-8'),
                headers=headers,
                method='POST'
            )
            with urllib.request.urlopen(req, timeout=15) as response:
                res_data = json.loads(response.read().decode('utf-8'))
                choices = res_data.get("choices", [])
                if choices:
                    return choices[0].get("message", {}).get("content", "").strip()
                return ""
        except Exception as e:
            raise RuntimeError(f"Falha ao contatar OpenRouter API: {e}")

class LLMAssistEngine:
    def __init__(self, agent: LLMAgent):
        self.agent = agent

    def route_query(self, query: str) -> Dict[str, Any]:
        try:
            raw_response = self.agent.generate_response(query)
            if "```json" in raw_response:
                raw_response = raw_response.split("```json")[1].split("```")[0]
            raw_response = raw_response.strip("` \n\r")
            return json.loads(raw_response)
        except Exception as e:
            return {
                "intent": "fallback",
                "command": None,
                "explanation": f"Erro no parsing da sugestão do modelo. Motivo: {e}"
            }
