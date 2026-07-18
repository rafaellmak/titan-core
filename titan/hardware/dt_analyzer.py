import re
import shutil
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional


class DeviceTreeAnalyzer:
    """Analisador de Device Tree.

    Faz três coisas, em ordem de confiabilidade:
    1. Análise estática (sempre roda, sem dependências): sintaxe básica,
       referências quebradas, propriedades obrigatórias, antipadrões.
    2. Compilação com dtc (se disponível): valida a sintaxe formal e
       produz um .dtb. Erros do dtc são coletados como findings.
    3. Validação de bindings com dt-validate (se disponível): confere
       se o .dtb está em conformidade com os schemas de binding do
       kernel. Avisos, não bloqueia.

    A análise estática roda em conjunto com dtc: se dtc compila, ainda
    procuramos problemas estáticos (ex: pinctrl faltando). Se dtc
    falha, a estática continua sendo útil como segundo sinal."""

    def __init__(self, workspace=None):
        self.workspace = workspace

    def _has_dtc(self) -> bool:
        return shutil.which("dtc") is not None

    def _has_dt_validate(self) -> bool:
        return shutil.which("dt-validate") is not None

    def _static_checks(self, content: str, dts_path: Path) -> List[Dict[str, Any]]:
        findings = []

        if not content.strip():
            return [{
                "severity": "Error",
                "component": "Static",
                "description": f"Arquivo vazio: {dts_path.name}",
            }]

        if "compatible" not in content and "/ {" in content:
            findings.append({
                "severity": "Warning",
                "component": "Root",
                "description": "Nó raiz sem propriedade 'compatible' — descrevendo apenas 'model'.",
            })

        if "/ {" in content and "model" not in content:
            findings.append({
                "severity": "Warning",
                "component": "Root",
                "description": "Nó raiz sem propriedade 'model'.",
            })

        if "#address-cells" not in content and "/ {" in content:
            findings.append({
                "severity": "Warning",
                "component": "AddressCells",
                "description": "Faltando #address-cells no nó raiz (necessário para mapear registradores).",
            })

        if "#size-cells" not in content and "/ {" in content:
            findings.append({
                "severity": "Warning",
                "component": "SizeCells",
                "description": "Faltando #size-cells no nó raiz (necessário para mapear registradores).",
            })

        if re.search(r'\bstatus\s*=\s*"(?!okay|disabled|ok|reserved)\w+"', content):
            findings.append({
                "severity": "Error",
                "component": "Status",
                "description": "Valor de 'status' inválido. Valores aceitos: 'okay', 'disabled', 'ok', 'reserved'.",
            })

        if re.search(r'\bstatus\s*=\s*"ok"', content):
            findings.append({
                "severity": "Info",
                "component": "Status",
                "description": "Uso de 'status = \"ok\"' (forma antiga). Prefira 'status = \"okay\"'.",
            })

        labels_defined = set(re.findall(r'^\s*(\w+):\s*[\w@]', content, re.MULTILINE))
        label_refs = set(re.findall(r'&(\w+)', content))
        undefined = label_refs - labels_defined
        for u in sorted(undefined):
            findings.append({
                "severity": "Error",
                "component": "LabelRef",
                "description": f"Referência a label '&{u}' não definida neste arquivo.",
            })

        if re.search(r'\binterrupts\s*=\s*<', content) and "interrupt-controller" not in content:
            findings.append({
                "severity": "Warning",
                "component": "Interrupts",
                "description": "Propriedade 'interrupts' presente mas nenhum nó declara 'interrupt-controller' (pode ser externo, mas vale conferir).",
            })

        if re.search(r'\bi2c@', content) and re.search(r'status\s*=\s*"okay"', content):
            if "pinctrl-0" not in content:
                findings.append({
                    "severity": "Warning",
                    "component": "Pinctrl",
                    "description": "Controlador I2C ativo sem pinagem pinctrl configurada (pode causar falha de probe).",
                })
            if "clock-frequency" not in content:
                findings.append({
                    "severity": "Info",
                    "component": "I2C",
                    "description": "I2C sem 'clock-frequency' explícita — o driver vai usar o fallback da plataforma.",
                })

        if re.search(r'\bspi@', content) and re.search(r'status\s*=\s*"okay"', content):
            if "#address-cells" not in content:
                findings.append({
                    "severity": "Warning",
                    "component": "SPI",
                    "description": "Controlador SPI ativo sem #address-cells configurado.",
                })

        node_names = re.findall(r'^\s*(\w[\w-]*)@', content, re.MULTILINE)
        seen = {}
        for n in node_names:
            seen[n] = seen.get(n, 0) + 1
        for name, count in seen.items():
            if count > 1:
                findings.append({
                    "severity": "Warning",
                    "component": "DuplicateNode",
                    "description": f"Nó '{name}' aparece {count}x. Pode ser válido (com sufixos de endereço) mas vale conferir.",
                })

        if "/dts-v1/" not in content and "/plugin/" not in content:
            findings.append({
                "severity": "Info",
                "component": "Header",
                "description": "Arquivo DTS sem '/dts-v1/;' no início. Recomendado para .dts standalone (overlays usam /plugin/).",
            })

        return findings

    def _run_dtc(self, dts_path: Path, dtb_path: Path) -> Optional[List[Dict[str, Any]]]:
        """Tenta compilar com dtc. Retorna lista de findings ou None se dtc não está disponível."""
        if not self._has_dtc():
            return [{
                "severity": "Warning",
                "component": "dtc missing",
                "description": "Compilador 'dtc' não encontrado no host. Análise estática rodando em paralelo.",
            }]

        print(f"🛠️  Compilando com dtc: {dts_path.name}")
        cmd = ["dtc", "-I", "dts", "-O", "dtb", "-o", str(dtb_path), str(dts_path)]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if res.returncode != 0:
                return [{
                    "severity": "Error",
                    "component": "dtc compiler",
                    "description": f"Falha de compilação semântica do DTS:\n{res.stderr.strip()[:1000]}",
                }]
            return []
        except FileNotFoundError:
            return [{
                "severity": "Warning",
                "component": "dtc missing",
                "description": "Compilador 'dtc' não encontrado no host (race com verificação anterior).",
            }]

    def _run_dt_validate(self, dtb_path: Path) -> List[Dict[str, Any]]:
        if not self._has_dt_validate() or not dtb_path.exists():
            return []
        print("🛡️  Validando bindings com dt-validate...")
        cmd = ["dt-validate", "-p", str(dtb_path)]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if res.returncode != 0 and res.stderr.strip():
                return [{
                    "severity": "Warning",
                    "component": "dt-validate binding",
                    "description": f"Divergência de binding detectada:\n{res.stderr.strip()[:500]}",
                }]
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        return []

    def analyze_dts(self, dts_path: Path) -> List[Dict[str, Any]]:
        findings = []
        if not dts_path.exists():
            return [{
                "severity": "Error",
                "component": "DTC",
                "description": f"Arquivo DTS não encontrado: {dts_path}",
            }]

        content = dts_path.read_text(encoding="utf-8", errors="ignore")

        dtc_findings = self._run_dtc(dts_path, dts_path.with_suffix(".dtb"))
        if dtc_findings is not None:
            findings.extend(dtc_findings)
        dtb_path = dts_path.with_suffix(".dtb")

        try:
            findings.extend(self._static_checks(content, dts_path))

            if not any(f["component"] == "dtc compiler" and f["severity"] == "Error" for f in findings):
                findings.extend(self._run_dt_validate(dtb_path))
        finally:
            if dtb_path.exists():
                dtb_path.unlink()

        return findings

    def report_findings(self, findings: List[Dict[str, Any]]):
        if not findings:
            print("✅ Device Tree validado com sucesso (estática + dtc).")
            return
        print(f"🚦 Análise de Device Tree ({len(findings)} achados):")
        for f in findings:
            color = "\033[91m" if f["severity"] == "Error" else \
                    "\033[93m" if f["severity"] == "Warning" else "\033[94m"
            reset = "\033[0m"
            print(f"{color}[{f['severity']}] {f['component']}{reset}: {f['description']}\n")
