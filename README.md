# Titan Core

> **Embedded Intelligence Runtime for Yocto/Buildroot engineering.**
> Event-driven. Agentic. With a Digital Twin and a Learning Loop.

[![CI](https://github.com/tecmak/titan-core/actions/workflows/ci.yml/badge.svg)](https://github.com/tecmak/titan-core/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Yocto](https://img.shields.io/badge/Yocto-compatible-blueviolet.svg)](https://www.yoctoproject.org/)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)

Titan watches a Yocto/Buildroot workspace 24/7, ingests events from the build system, the file system, and the kernel, dispatches them to modular skills, and runs a learning loop that gets sharper with every fix. It is not a chatbot. It is a runtime.

---

## What it is

Titan is a Python framework that sits between an engineer and an embedded Linux build. It does three things well:

1. **Observes** the workspace as a live graph (the *Digital Twin*).
2. **Decides** which skill to invoke when something changes (the *Skill Planner*).
3. **Learns** from every action so the next decision is better (the *Knowledge Engine* with its *Learning Loop*).

The default CLI runs offline against a real Yocto workspace. The optional FastAPI daemon exposes 15+ endpoints for CI/CD, dashboards, and external tooling.

---

## The pitch in one paragraph

Yocto build failures are a 3 AM problem. The log is gigabytes long, the recipe graph is hundreds of nodes deep, and the only person who has seen this exact error before retired last year. Titan reads the log, finds the failing recipe, maps its dependencies, checks for known CVE patterns, suggests a fix, and — if you say yes — applies it. Then it remembers what worked, bumps a confidence score, and indexes the failure as a `KnowledgeRecord` for the next run. Repeat a hundred times and the system starts suggesting fixes before you finish reading the error.

---

## Architecture

```
                           ┌──────────────────────────┐
                           │   Event Sources          │
                           │   (Bitbake, FS, kernel,  │
                           │    CI, manual API call)  │
                           └────────────┬─────────────┘
                                        │ events
                                        ▼
                           ┌──────────────────────────┐
                           │   LocalEventBus          │
                           │   (in-process pub/sub)   │
                           └────────────┬─────────────┘
                                        │
                                        ▼
                           ┌──────────────────────────┐
                           │   SkillPlanner           │
                           │   (routes by event type) │
                           └────────────┬─────────────┘
                                        │
            ┌──────────────┬────────────┼────────────┬──────────────┐
            ▼              ▼            ▼            ▼              ▼
     ┌──────────┐   ┌──────────┐ ┌──────────┐ ┌──────────┐  (your skill)
     │  Yocto   │   │   DTS    │ │ Security │ │ AutoFix  │     here
     │  Skill   │   │  Skill   │ │  Skill   │ │  Skill   │
     └─────┬────┘   └─────┬────┘ └─────┬────┘ └─────┬────┘
           │              │            │            │
           └──────────────┴─────┬──────┴────────────┘
                                ▼
              ┌──────────────────────────────────┐
              │       MultiLayerMemory           │
              │  ┌──────────┐  ┌──────────────┐  │
              │  │ state.db │  │ knowledge.db │  │
              │  └──────────┘  └──────────────┘  │
              │  ┌──────────────────────────────┐ │
              │  │       audit.db               │ │
              │  └──────────────────────────────┘ │
              └────────────┬─────────────────────┘
                           │
                ┌──────────┴──────────┐
                ▼                     ▼
        ┌──────────────┐      ┌──────────────────┐
        │ DigitalTwin  │      │ KnowledgeEngine  │
        │ (networkx +  │      │  + Learning Loop │
        │  event src)  │      │  + Similarity    │
        └──────────────┘      └──────────────────┘
```

### What lives where

| Path | What it does |
|------|--------------|
| `titan/core/event_bus.py` | In-process async pub/sub. The spine of the runtime. |
| `titan/core/planner.py` | `Skill` ABC + `SkillPlanner` that dispatches by event type. |
| `titan/core/digital_twin.py` | `networkx.DiGraph` rebuilt from an immutable JSONL event log. |
| `titan/core/knowledge_engine.py` | `KnowledgeRecord` store with similarity, confidence, and learning loop. |
| `titan/core/memory.py` | `MultiLayerMemory`: state, knowledge, audit. Three SQLite DBs. |
| `titan/skills/` | Pluggable skills. Add a file, register it, ship. |
| `titan/daemon.py` | FastAPI daemon. Event loop worker + 15+ REST endpoints. |
| `titan/enterprise/` | Auth, RBAC, exporter, hardening, Pydantic models. |
| `titan/diagnostics/` | Build-log rule engine. |
| `titan/recipes/` | Recipe indexer, dependency graph, SQLite-backed. |
| `titan/security/` | CVE monitor. |
| `titan/hardware/` | Device Tree analyzer. |
| `titan/runtime/` | dmesg analyzer. |
| `titan/llm_assist/` | LLM-as-intent-router (offline mock / Ollama / OpenRouter). |
| `titan/autofix/` | `FixTransaction` with sandbox rollback. |
| `titan/cli.py` | argparse entry point. The `titan` command. |

---

## Quick start

### CLI

```bash
git clone https://github.com/tecmak/titan-core
cd titan-core
pip install -e ".[dev]"

# Detect your Yocto workspace
titan info

# Diagnose a build failure
titan diagnose path/to/bitbake.log

# Search and inspect recipes
titan recipe search openssl
titan recipe deps openssl
titan recipe impact openssl

# Security scan
titan security

# Device Tree analysis
titan hardware path/to/board.dts

# dmesg analysis
titan runtime path/to/dmesg.log

# Explain a recipe
titan explain openssl

# LLM-assisted (offline, deterministic)
titan llm-assist "help me with the nothing provides error"
# LLM-assisted (local Ollama)
titan llm-assist "help me with the nothing provides error" --provider ollama --model qwen2.5:7b
# LLM-assisted (OpenRouter)
titan llm-assist "help me with the nothing provides error" --provider openrouter --model meta-llama/llama-3-8b-instruct:free
```

### Daemon (FastAPI)

```bash
# In one terminal
uvicorn titan.daemon:app --host 0.0.0.0 --port 8000

# In another
curl http://localhost:8000/health
# {"status":"healthy","version":"12.0"}

curl http://localhost:8000/api/v1/digital_twin/timeline?hours=24
curl -X POST http://localhost:8000/api/v1/workspace/scan
curl -X POST http://localhost:8000/api/v1/analyze
```

Or with Docker:

```bash
docker build -t titan-core .
docker run --rm -p 8000:8000 -v $(pwd)/.titan:/app/.titan titan-core
```

---

## CLI reference

| Command | What it does |
|---------|--------------|
| `titan info [--path DIR]` | Detect and report workspace type. |
| `titan diagnose LOG [--export-json F] [--export-pdf F]` | Run the diagnostic engine on a build log. |
| `titan recipe index` | Index all recipes in the workspace. |
| `titan recipe search NAME` | Search indexed recipes. |
| `titan recipe show NAME [--json]` | Show recipe details (JSON with `--json`). |
| `titan recipe deps NAME [--json]` | Print the dependency tree (JSON with `--json`). |
| `titan recipe impact NAME [--json]` | Print the reverse dependency tree (JSON with `--json`). |
| `titan action append-conf CONTENT` | Append a line to `conf/local.conf`. |
| `titan action add-layer PATH` | Add a layer to `bblayers.conf`. |
| `titan action patch-recipe RECIPE VAR VALUE` | Append a variable to a recipe's `.bbappend`. |
| `titan fix LOG` | Auto-fix a build failure (interactive). |
| `titan security [--stub] [--online] [--severity LEVEL] [--export-json F]` | Run the CVE monitor (offline stub or NVD online). |
| `titan hardware DTS` | Analyze a Device Tree. |
| `titan runtime DMESG_LOG` | Analyze a `dmesg` log. |
| `titan explain RECIPE [--json]` | Explain what a recipe does (JSON with `--json`). |
| `titan llm-assist PROMPT [--provider offline\|ollama\|openrouter]` | LLM-as-intent-router. |

---

## Adding a skill

A skill is a 30-line file. Register it once. Ship.

```python
# titan/skills/my_skill.py
from titan.core.planner import Skill
from titan.core.memory import MultiLayerMemory
from titan.core.digital_twin import DigitalTwin
from titan.core.knowledge_engine import KnowledgeEngine
from typing import Any, Dict

class MySkill(Skill):
    def can_handle(self, event_type: str, data: Dict[str, Any]) -> bool:
        return event_type == "my_event"

    async def execute(self, data, memory, digital_twin, knowledge_engine):
        memory.log_event("MY_SKILL_RAN", {"data": data})
        return {"status": "ok"}
```

Then register it in `titan/daemon.py`:

```python
from titan.skills.my_skill import MySkill
planner.register_skill(MySkill())
```

That's the whole contract.

---

## Design choices worth flagging

- **CLI is zero-dependency. Daemon is not.** The `titan` command runs against a real Yocto workspace with only the Python stdlib. The daemon pulls in FastAPI / Pydantic / uvicorn / networkx for the agentic layer. This split keeps the CLI usable in air-gapped and CI environments.
- **LLM is a router, not a generator.** The LLM is restricted to selecting from a closed set of pre-validated CLI actions. It never generates shell. The user always confirms before execution. This is non-negotiable for an engineering tool.
- **Deterministic offline mode.** The `DeterministicLLMMock` matches the user's prompt against regex patterns and returns the right Titan subcommand. Useful in restricted environments and as a CI safety net.
- **Event sourcing for the Digital Twin.** Every workspace change is appended to an immutable JSONL log. The live graph is a projection of that log. Snapshot at any point in time. Replay from any point in time.
- **The Knowledge Engine learns on every fix.** AutoFix writes a `KnowledgeRecord` with a confidence score. Successful runs bump the confidence and the success rate. Failure patterns emerge automatically. The system gets sharper the more you use it.

---

## Testing

```bash
pip install -e ".[dev]"
pytest --cov=titan tests/
```

The suite is async-aware (uses `pytest-asyncio`) and covers event sourcing, impact analysis, knowledge similarity, the learning loop, and the architectural sprint.

---

## Project status

12.0 "Agentic Evolution". Production-grade for individual use. Enterprise hardening (multi-tenant RBAC, OpenTelemetry, signed audit chain) is on the roadmap.

---

## License

MIT. See [LICENSE](LICENSE).
