# Guia Prático de Teste — Titan Core v12.0

> Teste todos os comandos e aprove a release.

---

## 1. Informações Básicas

```bash
# Versão
titan --version

# Ajuda geral
titan --help

# Ajuda de um comando específico
titan recipe --help
titan security --help
titan twin --help
titan explain --help
```

---

## 2. Workspace

```bash
# Detecta o workspace atual (Yocto ou Buildroot)
titan info
```

**Esperado:** Mostra o tipo de workspace e o diretório.

---

## 3. Recipes

### 3.1 Indexar

```bash
# Indexa todas as recipes no banco local
# (obrigatório antes de qualquer comando recipe)
titan recipe index
```

**Esperado:** Indexa receitas da workspace. Pode levar alguns minutos.

### 3.2 Buscar

```bash
# Lista todas as recipes
titan recipe search

# Busca por nome
titan recipe search openssl

# Busca com saída JSON
titan recipe search openssl --json
```

**Esperado:** Retorna recipes encontradas com nome e versão.

### 3.3 Mostrar detalhes

```bash
# Detalhes de uma recipe
titan recipe show openssl

# Com saída JSON
titan recipe show openssl --json
```

**Esperado:** PV, Licença, DEPENDS, RDEPENDS, SRC_URI, INHERITS, caminho do arquivo.

### 3.4 Dependências

```bash
# Árvore de dependências
titan recipe deps openssl

# Formato JSON
titan recipe deps openssl --json
```

**Esperado:** Lista do que a recipe precisa para compilar.

### 3.5 Impacto

```bash
# Quem depende desta recipe
titan recipe impact openssl

# Formato JSON
titan recipe impact openssl --json
```

**Esperado:** Lista de recipes que QUEBRAM se esta for alterada.

---

## 4. Explicação

```bash
# Explica propósito, licença, dependências e risco de alterar
titan explain openssl

# Com saída JSON
titan explain openssl --json
```

**Esperado:** Licença, DEPENDS, SRC_URI, status (root ou dependência), impacto.

---

## 5. Diagnóstico de Build

> Requer um log de build do Yocto

```bash
# Exemplo com log real (substitua pelo caminho do seu log)
titan diagnose caminho/do/log/build.log

# Exporta relatório
titan diagnose build.log --export-json relatorio.json
titan diagnose build.log --export-pdf relatorio.pdf
```

**Esperado:** Problemas encontrados com severidade, regra e sugestão.

---

## 6. Segurança (CVE)

### 6.1 Offline (stub, sem internet)

```bash
# Varredura offline com dados de exemplo
titan security --stub

# Filtrando por severidade
titan security --stub --severity critical
titan security --stub --severity high critical

# Exportando para JSON
titan security --stub --export-json cves.json
```

**Esperado:** CVEs conhecidos nos pacotes do workspace, com severidade e descrição.

### 6.2 Online (requer internet)

```bash
# Consulta API NVD (com cache de 24h)
titan security --online

# Filtrado por severidade
titan security --online --severity critical
```

**Esperado:** CVEs reais do NVD para os pacotes do workspace.

---

## 7. Hardware (Device Tree)

> Requer um arquivo .dts

```bash
titan hardware caminho/para/device-tree.dts
```

**Esperado:** Análise de nós, compatibilidades, interrupções, GPIOs, clocks.

---

## 8. Runtime (Kernel)

> Requer um log dmesg

```bash
titan runtime caminho/do/dmesg.log
```

**Esperado:** Análise de OOM, drivers, hardware errors, USB, network.

---

## 9. Auto-Fix

> Requer um log de build com erro

```bash
titan fix caminho/do/log-de-erro.log
```

**Esperado:** Modo interativo — mostra erro e permite aplicar correção.

---

## 10. Ações no Workspace

> ⚠️ Estas ações MODIFICAM arquivos do workspace

```bash
# Adiciona linha ao conf/local.conf
titan action append-conf 'PACKAGECONFIG:append:pn-openssl = " eng"'

# Adiciona layer ao bblayers.conf
titan action add-layer /caminho/para/meta-layer

# Aplica patch em uma recipe (modo interativo)
titan action patch-recipe openssl EXTRA_OECONF '--with-test'

# Força sem confirmação
titan action patch-recipe -y openssl EXTRA_OECONF '--with-test'
```

---

## 11. LLM Assist

```bash
# Modo offline/determinístico (não requer internet)
titan llm-assist "ajuda com openssl"

# Com Ollama local
titan llm-assist "analisar erro de compilação" --provider ollama --model qwen2.5:7b

# Com OpenRouter
titan llm-assist "diagnosticar problema" --provider openrouter --model meta-llama/llama-3-8b-instruct:free --key sk-...
```

---

## 12. Digital Twin

```bash
# Cria um snapshot do estado atual
titan twin snapshot v1.0 --note "Estado inicial após indexação"

# Lista snapshots
titan twin snapshots

# Compara dois snapshots
titan twin compare v1.0 v2.0

# Impacto de alterar uma entidade
titan twin impact openssl
titan twin impact openssl --json
```

---

## 13. Telemetria

```bash
# Métricas da sessão atual
titan telemetry

# Salva trace
titan telemetry --save
```

---

## Checklist de Aprovação

- [ ] `titan --version` mostra v12.0.0
- [ ] `titan info` detecta workspace
- [ ] `titan recipe index` funciona
- [ ] `titan recipe search openssl` retorna resultados
- [ ] `titan recipe show openssl` mostra detalhes
- [ ] `titan recipe deps openssl` mostra dependências
- [ ] `titan recipe impact openssl` mostra dependentes
- [ ] `titan explain openssl` explica a recipe
- [ ] `titan security --stub` mostra CVEs
- [ ] `titan --json` flags funcionam (show, search, deps, impact, explain)
- [ ] `twin snapshot` + `twin snapshots` + `twin compare` funcionam
- [ ] `titan telemetry` mostra métricas
