# Changelog

## v12.0.0 — "Agentic Evolution" (2025-04)

### Features
- **CLI overhaul** — unified `--workspace/-w` flag propagated to all subcommands, consistent exit codes
- **`titan recipe`** — `show`, `search`, `deps`, `impact` with tree output + `--json` flag
- **`titan recipe index`** — indexes all recipes from Yocto/Buildroot workspaces into SQLite
- **`titan security`** — offline stub + `--online` NVD scanning with 24h cache, rate-limit, pagination
- **`titan explain`** — recipe explanation with metadata, fallback impact analysis + `--json`
- **`titan diagnose`** — build log diagnosis with `--export-json` / `--export-pdf`
- **`titan fix`** — interactive auto-fix engine with knowledge recording
- **`titan runtime`** — dmesg log analyzer with 17+ pattern rules
- **`titan hardware`** — Device Tree Source analyzer
- **`titan llm-assist`** — LLM-as-intent-router with offline, Ollama, and OpenRouter providers
- **`titan twin`** — Digital Twin: snapshots, diff, compare, impact analysis
- **Knowledge Graph** — deterministic `depends_on` / `belongs_to` edge store with RecipeDB sync
- **Digital Twin** — event-sourced graph with snapshot/replay, fallback to RecipeDB
- **Buildroot support** — Config.in parser, .mk parser, toolchain detection, diagnostics
- **Learning Loop** — Knowledge Engine, metrics, ranking, replay, recommender, feedback

### Fixes
- `recipe show` was a no-op — now displays full recipe metadata
- `security` used hardcoded fake CVEs — now uses real stub DB + optional NVD online
- `hardware` static analysis was dead code — rewritten DTS analyzer
- `autofix` picked wrong recipe name + required bitbake sandbox — fixed both
- `runtime` OOM pattern never matched — rewritten with 17 new dmesg rules
- `llm-assist` crashed on no-TTY (EOFError) — reads stdin, weak classifier hardened
- 3 production bugs in the v12 codebase fixed (circular import, missing auth module, graph sync)
- `daemon` API: POSTs accept JSON body, GETs validate params, 404 on missing routes
- `action` subcommands: CLI UX improved, safety confirmation, override char logic fixed

### CI / DevOps
- Multi-stage Dockerfile (slim build + runtime, non-root user, healthcheck)
- GitHub Actions CI workflow (ruff lint + pytest 337 tests)
- `.gitignore` coverage for all test artifacts, venvs, IDE files

### Breaking changes
- Removed `titan/api/` (empty directory, replaced by `titan/daemon.py`)
- Removed `presentation_v11/` and old `docs/apresentacao_titan_v11.md`
- `titan.security` module renamed keys from `id` to `cve_id` for consistency

### Compatibility
- Python 3.10+ (tested 3.10–3.12)
- Yocto Kirkstone+ / Buildroot 2023+
- Works on air-gapped systems (CLI mode), network only for NVD scanning or LLM
