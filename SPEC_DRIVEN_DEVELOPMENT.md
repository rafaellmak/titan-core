# TITAN ENGINEERING STANDARD
## Spec-Driven Development (SDD) — v2.0

**Status:** Mandatory
**Applies To:** All Titan Core modules, CLI, Daemon, Skills, Validation, Learning, and future components.

---

## 1. Project Vision

Titan is an **Embedded Intelligence Runtime** for Yocto/Buildroot engineering. It transforms a traditional build system diagnostic tool into an **assisted engineering platform** with:

- **Deterministic validation** — every skill execution is validated against domain-specific criteria
- **Persistent experience learning** — error patterns are extracted, normalized, and stored as auditable knowledge
- **Contextual recommendation** — fixes are ranked by workspace context (arch, toolchain, board) and historical feedback
- **Closed feedback loop** — every recommendation outcome is recorded and used to improve future suggestions
- **No external AI dependencies at the core** — all learning and recommendation is deterministic and audit-friendly

---

## 2. Architectural Principles

### Principle 1 — Validation Before Learning
No error pattern enters the learning system without first passing through the Validation Harness. Learning operates exclusively on validated history records.

### Principle 2 — Digital Twin Is the Source of Truth
The Digital Twin graph maintains the authoritative representation of workspace state. All skills query and update the twin, never inconsistent local state.

### Principle 3 — Knowledge Is Aggregated, Not Raw
The Knowledge Engine stores learned patterns (aggregated statistics), not raw events. Raw validation history lives in ValidationDB; PatternDB only stores promoted patterns that exceed quality thresholds.

### Principle 4 — Normalization Is Mandatory
Every error fingerprint must be normalized before entering the learning pipeline. Raw text variations of the same root cause collapse to a single canonical fingerprint.

### Principle 5 — Evidence-Based Recommendations
Every recommendation must cite:
- Occurrence count
- Historical success rate
- Average validation score
- Contextual match rank

### Principle 6 — Learning Is Deterministic
No randomness, no LLM, no probabilistic models. All learning thresholds (`MIN_OCCURRENCES`, `MIN_SCORE`, `MIN_SUCCESS_RATE`) are explicit constants.

### Principle 7 — Feedback Is Required
Every recommendation must be followed by a feedback record. Without feedback, the ranking engine operates with incomplete information.

### Principle 8 — Single Source of Configuration
`pyproject.toml` is the sole source of dependency and packaging metadata. No `requirements.txt`, no `setup.py`.

---

## 3. Component Responsibilities

### 3.1 Digital Twin (`titan/core/digital_twin.py`)

**Responsibility:** Maintain a graph representation of the workspace (recipes, packages, dependencies, layers) that serves as the single source of truth for current system state.

**Key contracts:**
- `emit_event(event_type, data)` — Record an event and update the graph
- `get_graph()` — Return the `networkx.DiGraph`
- `query_impact(node_id)` — Return affected nodes for a given component
- `create_snapshot(snapshot_id, note)` — Persist graph state for later recovery

**Boundaries:**
- Does NOT store learned knowledge (that is the Knowledge Engine's role)
- Does NOT store validation history (that is ValidationDB's role)
- Does NOT execute skills (that is the Planner's role)
- **Known gap:** Skills write to the twin via `emit_event()` but currently do NOT query it. The query API (`query_dependencies`, `query_impact`, `get_graph`) exists but is unused in production paths. Skills receive the `digital_twin` parameter but do not read from it.

### 3.2 Knowledge Engine (`titan/core/knowledge_engine.py`)

**Responsibility:** Store and retrieve learned problem/solution patterns as aggregated knowledge records.

**Key contracts:**
- `add_knowledge(record)` — Insert or update a knowledge record by problem signature
- `find_similar_knowledge(description, limit)` — Keyword-based similarity search
- `get_ranked_knowledge(limit)` — Return top-N records by confidence/success
- `recognize_failure_patterns(min_occurrences)` — Surface patterns above occurrence threshold

**Boundaries:**
- Operates on raw problem signatures (not normalized fingerprints — that is the Learning Engine's domain)
- Currently disconnected from the Learning Engine pipeline (gap)
- KnowledgeRecords are created by skills via `AutoFixSkill` and `DiagnosticEngine`

### 3.3 Memory (`titan/core/memory.py`)

**Responsibility:** Three-layer persistent memory: State (key-value), Knowledge (categorized entries), Audit (event log).

**Key contracts:**
- `update_state(key, value)` / `get_state(key)` — State layer CRUD
- `add_knowledge(category, topic, content, tags)` — Knowledge layer
- `log_event(event_type, details, status)` — Audit layer

**Boundaries:**
- Memory knowledge layer is separate from KnowledgeEngine and Learning Engine
- Audit layer feeds into DigitalTwin events

### 3.4 Validation Harness (`titan/validation/harness.py`)

**Responsibility:** Wrap all skill execution with deterministic validation, scoring, and history recording.

**Key contracts:**
- `execute(skill, data, memory, digital_twin, knowledge_engine, ...)` — Run skill, validate, record in history. Returns `(SkillResult, ValidationResult)`
- `get_report()` — Formatted validation report
- `validate_dispatch(planner, event_type, data, harness, workspace)` — Dispatch events to skills through harness

**Required validators (defined in `titan/validation/validators.py`):**
- `BuildrootValidator` — `.config` existence, output structure, toolchain detection, kernel image
- `YoctoValidator` — workspace detection, recipe indexing, build dir, mutation validity
- `DTSValidator` — dtc compilation, binding checks, no critical warnings
- `SecurityValidator` — scan completed, no critical CVEs

**Scoring** (`titan/validation/score.py`):
- Weighted percentage based on check weights
- Classification: excellent (≥90), good (≥70), needs_review (≥50), rejected (<50)

### 3.5 Learning Engine (`titan/learning/`)

#### 3.5.1 Error Normalizer (`titan/learning/normalizer.py`)

**Responsibility:** Map raw error text to canonical fingerprints using deterministic regex patterns.

**Canonical categories:**
- BuildrootError → BUILDROOT_MISSING_PACKAGE, BUILDROOT_TOOLCHAIN_ERROR, BUILDROOT_KERNEL_ERROR, BUILDROOT_CONFIG_ERROR
- YoctoError → YOCTO_NOTHING_PROVIDES, YOCTO_PARSE_ERROR, YOCTO_TASK_FAILURE, YOCTO_QA_WARNING
- DTSError → DTS_COMPILATION_ERROR, DTS_BINDING_ERROR
- SecurityError → SECURITY_CRITICAL_CVE, SECURITY_HIGH_CVE

**Format:** `CATEGORY_TYPE:extracted_package_or_detail`

**Fallback:** If no pattern matches, extract significant keywords and join with underscores.

**Quality metrics** (`titan/learning/metrics.py`):
- Compression ratio: unique_raw / unique_canonical
- Collision count: fix_signatures that differ but map to the same canonical
- Fragmentation count: same raw fingerprint mapping to different canonicals

#### 3.5.2 PatternDB (`titan/learning/patterns.py`)

**Responsibility:** SQLite-backed storage for learned patterns. Stores aggregated statistics only.

**Schema:** `learned_patterns` table with fingerprint (PK), category, occurrences, success_rate, average_score, best_fix, first_seen, last_seen, top_fixes (JSON).

**Thresholds for promotion:**
- `MIN_OCCURRENCES = 3`
- `MIN_SCORE = 60.0`
- `MIN_SUCCESS_RATE = 0.60`

#### 3.5.3 Learning Engine (`titan/learning/engine.py`)

**Responsibility:** Read validation history, extract patterns, promote to PatternDB.

**Key contracts:**
- `learn_all()` — Batch process all history, group by normalized fingerprint, promote patterns meeting thresholds
- `learn_from_run(run)` — Incremental learning from a single validation run
- `suggest(error_text, limit)` — Search PatternDB by raw or normalized fingerprint
- `top_knowledge(category, limit)` — Return top patterns
- `stats()` — Pattern count by category

**Pipeline:** History → Normalizer → Group by fingerprint → Build pattern (aggregate score, rate, fixes) → Check thresholds → Upsert to PatternDB → Record workspace context

#### 3.5.4 PatternContextDB (`titan/learning/context.py`)

**Responsibility:** Track pattern performance by workspace context (arch, toolchain, category, distro, kernel, board).

**Ranking:** `search_by_context()` uses weighted SQL:
- arch match = 2 points
- toolchain match = 2 points
- board match = 2 points
- category, distro, kernel match = 1 point each

#### 3.5.5 Feedback Loop (`titan/learning/feedback.py`)

**Responsibility:** Record every recommendation outcome and compute acceptance rates.

**Schema:** `feedback_loop` table with id, timestamp, fingerprint, recommended_fix, applied_fix, accepted (bool), score, context.

**Key contracts:**
- `record(fingerprint, recommended_fix, applied_fix, accepted, score, context)` — Record outcome
- `fix_effectiveness(fingerprint)` — Return acceptance_rate and best_fix

### 3.6 Ranking Engine (`titan/learning/ranking.py`)

**Responsibility:** Combine three signals into a single rank score (0-100).

**Formula:**
- Raw pattern quality (0-40): `success_rate * 20 + min(average_score / 5, 20)`
- Context similarity (0-30): `similarity * 20 + min(context_success_rate * 10, 10)` or neutral 15 if no context
- Feedback history (0-30): `acceptance_rate * 30`

### 3.7 Recommender (`titan/learning/recommender.py`)

**Responsibility:** Produce ranked, evidence-based fix recommendations.

**Key contracts:**
- `recommend(error_text, limit, context)` — Get patterns from LearningEngine, rank, add confidence score
- `recommend_by_fingerprint(fingerprint, limit, context)` — Direct lookup
- `explain(recommendation)` — Human-readable explanation
- `top_recommendations(category, limit)` — Top patterns

**Confidence formula:** `occurrences/50 * 0.3 + score/100 * 0.35 + success_rate * 0.35`

### 3.8 Replay Runner (`titan/learning/replay.py`)

**Responsibility:** Replay historical validation runs through the learning pipeline to measure accuracy.

**Metrics:** top-1 accuracy, top-3 accuracy, recommendation recall

### 3.9 Benchmark (`titan/learning/benchmark.py`)

**Responsibility:** Compute aggregate learning score from replay results.

**Score:** `top1_accuracy * 0.5 + top3_accuracy * 0.3 + recall * 0.2`

**Grade:** A (≥90), B (≥75), C (≥60), D (≥40), F (<40)

---

## 4. Mandatory Execution Flow

```
External Event (build failure, file change, scan request)
    │
    ▼
SkillPlanner.dispatch()
    │
    ▼
Skill.can_handle() → Skill.execute()
    │
    ▼
ValidationHarness.execute()  ← INTEGRATION GAP: not yet connected to CLI/daemon
    │
    ├── Skill result
    ├── Validation (validator → checks → scorer → grade)
    └── History (ValidationHistory.finish_run → ValidationDB)
            │
            ▼
        LearningEngine.learn_from_run()  [incremental] or learn_all() [batch]
            │
            ├── ErrorNormalizer.normalize()
            ├── PatternDB.upsert_pattern()  [if thresholds met]
            ├── PatternContextDB.upsert_context()
            └── (future: KnowledgeEngine integration)
                    │
                    ▼
                Recommender.recommend()  [on request]
                    │
                    ├── RankingEngine.rank()
                    ├── FeedbackLoop.fix_effectiveness()
                    └── → evidence-based suggestion
                            │
                            ▼
                        FeedbackLoop.record()  [after fix applied]
```

---

## 5. Validation Requirements

### 5.1 All Skill Execution Must Be Validated
No skill result leaves the harness without passing through a registered validator.

**Integration status:** The `ValidationHarness` is fully implemented and tested (46 tests) but is NOT yet connected to the CLI (`titan/cli.py`) or daemon (`titan/daemon.py`) execution paths. Currently only used directly in tests. This is the highest-priority integration item.

### 5.2 Validators Are Domain-Specific
Each workspace type (Buildroot, Yocto) and each analysis type (DTS, Security) has its own validator extending `BaseValidator`.

### 5.3 Scoring Is Weighted
Each validation check has a weight. The Scorer computes a weighted percentage. Score < 50 is rejected.

### 5.4 History Is Mandatory
Every validated execution must be recorded in ValidationDB for future learning.

### 5.5 Error Signatures Must Be Extracted
Every skill result must have its error category and fingerprint extracted via `ErrorSignature.from_raw()`.

---

## 6. Learning Requirements

### 6.1 Normalization Before Learning
All error fingerprints must pass through `ErrorNormalizer.normalize()` before any aggregation or storage in PatternDB.

### 6.2 Thresholds Guard Promotion
No pattern is promoted to PatternDB unless it exceeds ALL three thresholds:
- `occurrences >= 3`
- `average_score >= 60.0`
- `success_rate >= 0.60`

### 6.3 Incremental and Batch Learning
The Learning Engine supports both modes:
- `learn_all()` for batch processing of existing history
- `learn_from_run()` for incremental learning after each validation

### 6.4 Context Must Be Recorded
Every promoted pattern must have its workspace context recorded in PatternContextDB when available (arch, toolchain, board).

### 6.5 Feedback Is the Completion Signal
A learning cycle is only complete when feedback is recorded for the recommendation.

---

## 7. Normalization Requirements

### 7.1 Deterministic Only
Normalization must use compiled regex patterns. No fuzzy matching, no LLM, no similarity thresholds.

### 7.2 Canonical Format
Format: `CATEGORY_TYPE:extracted_detail`
Example: `BUILDROOT_MISSING_PACKAGE:openssl`

### 7.3 Fallback Strategy
If no pattern matches the error text, extract significant words (>2 chars, max 4) and join with underscores. If that also fails, uppercase the entire text with underscore separators.

### 7.4 Extensibility
New patterns can be added via `add_rule(category, canonical, regex)` at runtime without code changes.

### 7.5 Metrics Required
Normalization quality must be monitored via `NormalizationMetrics`:
- Compression ratio target: > 2.0x (one canonical should cover multiple raw variations)
- Collision count target: 0 (different fixes should never share a canonical)
- Fragmentation count target: 0 (same raw error should always produce the same canonical)

---

## 8. Recommendation Requirements

### 8.1 Evidence-Based Output
Every recommendation must include: fingerprint, category, occurrences, success_rate, average_score, best_fix, rank_score, confidence.

### 8.2 Ranking Combines Three Signals
- Pattern quality (occurrences, success rate, score)
- Workspace context match (arch, toolchain, board similarity)
- Feedback history (acceptance rate for this fingerprint)

### 8.3 Confidence Score
Every recommendation must include a confidence score (0.0-1.0) based on:
- `occurrences / 50 * 0.3`
- `normalized score * 0.35`
- `success_rate * 0.35`

### 8.4 Fallback Behavior
If no pattern matches the error text:
1. Fall back to normalized fingerprint search
2. If still empty, return empty list (do NOT fabricate recommendations)

---

## 9. Testing Policy

### 9.1 Test Baseline
Current: **282 tests, 0 failures** (across 21 test files)

### 9.2 Required Coverage per Component

| Component | Min Tests | Current | Test File(s) |
|---|---|---|---|
| Validation Harness | 30 | 46 | test_validation_harness.py |
| Learning Engine | 15 | 20 | test_learning_engine.py |
| PatternDB | 6 | 6 | test_learning_engine.py |
| NormalizationMetrics | 8 | 10 | test_learning_metrics.py |
| SyntheticDataset | 6 | 7 | test_learning_metrics.py |
| ReplayRunner | 6 | 6 | test_learning_replay.py |
| LearningBenchmark | 4 | 4 | test_learning_replay.py |

### 9.3 Zero-Failure Policy
No code may be merged that reduces the passing test count. A failing test is a blocking bug.

### 9.4 Test Types Required
- **Unit tests** for all dataclass/utility methods
- **Integration tests** for pipeline flows (history → learning → recommend)
- **Synthetic dataset tests** for benchmark accuracy measurement

### 9.5 No LLM in Tests
All tests must be deterministic. No test may call an external API or depend on LLM output.

---

## 10. Forbidden Architectural Decisions

| Decision | Reason |
|---|---|
| Storing raw events in PatternDB | PatternDB stores aggregated knowledge only — raw events live in ValidationDB |
| Bypassing the Validation Harness | Every skill execution must be validated |
| Using fuzzy/LLM for normalization | Would break auditability and determinism |
| Removing learning thresholds | Thresholds prevent promoting bad patterns with few occurrences |
| Skipping feedback recording | Without feedback, the ranking engine cannot improve |
| Mixing context data into PatternDB | Context is stored in PatternContextDB to keep each store single-purpose |
| Direct database access from skills | Skills must go through Planner / Harness |
| Storing secrets in code | Auth uses `.env` / environment variables |
| Hardcoding workspace paths | All paths must be configurable or auto-detected |
| Skipping tests for new components | 0-failure policy is enforced |

---

## 11. Roadmap and Future Evolution Rules

### 11.1 Evolution Priority
1. **Architecture stability** — no breaking changes without deprecation period
2. **Reliability** — increase synthetic dataset coverage, add stress tests
3. **Validation** — add validators for remaining skill types
4. **Knowledge reuse** — connect Learning Engine to Knowledge Engine
5. **Automation** — self-tuning thresholds based on feedback trends
6. **Features** — new skills, new normalizer patterns, new contexts

### 11.2 Connecting the Knowledge Engine
The Knowledge Engine (`titan/core/knowledge_engine.py`) and the Learning Engine (`titan/learning/`) currently operate independently. A future integration step must:
- Promote Learning Engine patterns into KnowledgeEngine as KnowledgeRecords
- Allow KnowledgeEngine to query Learning Engine for contextual ranking
- Unify the feedback signal across both systems

### 11.3 Threshold Self-Tuning
A future version should analyze feedback trends to suggest threshold adjustments:
- If acceptance_rate is consistently high (>0.9) for patterns near threshold boundaries, lower thresholds
- If acceptance_rate is consistently low (<0.3) for promoted patterns, raise thresholds

### 11.4 Forward Compatibility
- All new normalizer patterns should be additive — never remove existing patterns without deprecation
- SQLite schemas must use `CREATE TABLE IF NOT EXISTS` and additive migrations only
- CLI output must be backward-compatible or version-flagged

### 11.5 Deprecation Policy
- Mark deprecated components in code with a comment and a `FutureWarning`
- Keep deprecated code for at least 2 minor versions before removal
- Example: `titan/legacy/runners/` contains preserved but deprecated runner classes

---

## 12. Version Convention

| Version | Focus |
|---|---|
| v12 | Current — Learning Engine + Validation Harness + Feedback |
| v13 | Knowledge Engine integration |
| v14 | Threshold self-tuning + advanced metrics |
| v15 | Multi-workspace orchestration |

*This document is authoritative. All development decisions must be traceable to a section herein.*
