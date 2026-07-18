## Description
What does this PR do, and why?

## Type of change
- [ ] Bug fix (non-breaking change that fixes an issue)
- [ ] New feature (non-breaking change that adds capability)
- [ ] Breaking change (fix or feature that changes existing behavior)
- [ ] Documentation update
- [ ] Refactor (no functional change)

## Affected modules
- [ ] `titan/core/` (event_bus, planner, digital_twin, knowledge_engine, memory)
- [ ] `titan/skills/` (yocto, dts, security, autofix)
- [ ] `titan/enterprise/` (api, auth, models)
- [ ] `titan/diagnostics/` / `titan/runtime/` / `titan/security/`
- [ ] `titan/cli.py`
- [ ] Tests
- [ ] Docs

## How was it tested?
- [ ] Unit tests added/updated
- [ ] Integration test against a real Yocto workspace
- [ ] Manual CLI run: `titan ...`
- [ ] Manual API run: `curl http://localhost:8000/...`

## Checklist
- [ ] Code follows the existing style (no surprise dependencies, async-aware)
- [ ] New skills implement `can_handle()` and `execute()` per `Skill` ABC
- [ ] All new endpoints have RBAC + Pydantic models
- [ ] Self-review done (comments where the why isn't obvious)
- [ ] Docs updated (README, docs/, presentation/ if architectural)
