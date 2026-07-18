# Architecture Decision Records (ADR)

**Project:** Titan Core v12
**Date:** 2025-06-20
**Status:** Active

---

## ADR-001: Validation Before Learning

**Status:** Accepted

**Context:** Early versions of Titan allowed skills to write directly to the knowledge base without validation. This caused noise in the knowledge store: incorrect fixes, false positives, and low-quality patterns degraded the recommendation quality over time. The system needed a gate that every execution must pass before its results are eligible for learning.

**Decision:** Every skill execution MUST pass through the `ValidationHarness` before its result can reach the Learning Engine. The harness:

1. Executes the skill inside a controlled wrapper
2. Selects a domain-specific validator (`BuildrootValidator`, `YoctoValidator`, `DTSValidator`, `SecurityValidator`)
3. Runs validation checks with weighted scoring
4. Records the result in `ValidationDB` via `ValidationHistory`
5. Only recorded runs can be consumed by `LearningEngine.learn_all()` or `learn_from_run()`

**Consequences:**
- Positive: Learning operates only on validated, scored, auditable data
- Positive: Validators can evolve independently from skills
- Positive: History provides a complete audit trail for every decision
- Negative: Added latency to every skill execution (validation + DB write)
- Negative: Validators must be maintained alongside skills (one more file per domain)

**Alternatives Rejected:**
- *Skills write directly to learning* — rejected because it bypasses quality gates
- *Learning validates its own input* — rejected because validation is domain-specific (requires workspace knowledge, not just error text)
- *Probabilistic scoring* — rejected in favor of deterministic weighted checks

**Implementation:** `titan/validation/harness.py:52` — `execute()` method wraps skill, runs validator, records history. `titan/validation/validators.py:14-20` — `BaseValidator` ABC with 4 concrete implementations.

---

## ADR-002: Digital Twin Is the Source of Truth for Current System State

**Status:** Accepted

**Context:** Multiple components needed to know the current workspace state (installed packages, recipes, dependencies, configuration). Each component was caching state independently, leading to inconsistencies. For example, a skill could read stale recipe data while the workspace had already changed.

**Decision:** The `DigitalTwin` (`titan/core/digital_twin.py`) is the single authoritative source for current workspace state. It maintains a `networkx.DiGraph` that is updated by every skill execution and persisted as JSONL event logs + GML snapshots.

**Key rules:**
- Skills may query the Digital Twin but must not maintain their own state caches
- All state mutations must go through `emit_event()` which updates the graph atomically
- Snapshots capture graph + event log for restore and reproducibility

**Consequences:**
- Positive: Single consistent view of workspace state across all components
- Positive: Snapshots enable reproducibility and rollback
- Positive: Timeline events provide a full audit trail of state changes
- Negative: Added complexity — skills must emit events and query the twin
- Negative: `networkx` dependency is required even for CLI-only use

**Alternatives Rejected:**
- *Each skill caches its own state* — rejected due to inconsistency bugs
- *Database-only state* — rejected because the graph structure is essential for dependency/impact analysis
- *Event sourcing without graph* — rejected because impact queries (`what depends on X?`) require graph traversal

**Implementation:** `titan/core/digital_twin.py:28` — `DigitalTwin` class with `nx.DiGraph`, event emission, snapshot support. Events tracked: `layer_added`, `recipe_added`, `dependency_added`, `buildroot_workspace_scanned`, `buildroot_package_added`, etc.

---

## ADR-003: Knowledge Engine Stores Learned Experience Only

**Status:** Accepted

**Context:** The codebase had two separate storage systems that were conflated: the Knowledge Engine (`titan/core/knowledge_engine.py`) and PatternDB (`titan/learning/patterns.py`). The Knowledge Engine was being used for both immediate problem-solving records and long-term learned patterns, while PatternDB was emerging as the dedicated store for aggregated learning.

**Decision:** Clearly separate the two stores:

| Aspect | Knowledge Engine | PatternDB |
|---|---|---|
| **Type** | Raw problem/solution records | Aggregated pattern statistics |
| **Schema** | `problem_signature`, `root_cause`, `action_taken`, `outcome` | `fingerprint`, `occurrences`, `success_rate`, `average_score`, `best_fix` |
| **Created by** | Skills (`AutoFixSkill`, `DiagnosticEngine`) | Learning Engine (`LearningEngine.learn_all()`) |
| **Consumed by** | `find_similar_knowledge()`, `get_ranked_knowledge()` | `suggest()`, `top_patterns()` |
| **Thresholds** | None (any skill can create) | `MIN_OCCURRENCES=3`, `MIN_SCORE=60`, `MIN_SUCCESS_RATE=0.60` |

The Knowledge Engine stores raw experience (what happened, what was tried). PatternDB stores distilled knowledge (what reliably works).

**Consequences:**
- Positive: Clear boundary — raw vs. aggregated
- Positive: PatternDB can enforce quality thresholds; Knowledge Engine cannot
- Positive: Two separate SQLite databases with independent schemas
- Negative: Two systems to maintain and query
- Negative: No automatic promotion from Knowledge Engine to PatternDB (gap)

**Alternatives Rejected:**
- *Single store with a "status" field (raw/verified/promoted)* — rejected because it couples two different lifecycle stages
- *PatternDB as the only store* — rejected because immediate problem-solving records (knowledge) should not wait for threshold accumulation

**Implementation:**
- Knowledge Engine: `titan/core/knowledge_engine.py:48` — `KnowledgeEngine` with SQLite-backed `knowledge` table
- PatternDB: `titan/learning/patterns.py:55` — `PatternDB` with SQLite-backed `learned_patterns` table
- Note: These two stores are NOT yet connected — see ADR-008 gap

---

## ADR-004: Error Normalization Is Mandatory Before Learning

**Status:** Accepted

**Context:** Raw error messages like `"missing openssl"`, `"openssl not found"`, and `"libssl dependency missing"` represent the same root cause but are stored as separate fingerprints. Without normalization, the Learning Engine would treat these as three unrelated patterns, fragmenting knowledge and never reaching the `MIN_OCCURRENCES=3` threshold.

**Decision:** All error fingerprints MUST pass through `ErrorNormalizer.normalize()` before any learning operation:

1. The normalizer compiles regex patterns per domain (Buildroot, Yocto, DTS, Security)
2. Each pattern maps to a canonical form like `BUILDROOT_MISSING_PACKAGE:openssl`
3. If no pattern matches, a deterministic fallback extracts significant keywords
4. Normalization is applied in `_group_by_fingerprint()` (batch) and `learn_from_run()` (incremental)

**Key patterns implemented:**
- `missing (.+)`, `package (.+) not found`, `(.+) dependency missing` → `BUILDROOT_MISSING_PACKAGE:<pkg>`
- `nothing provides (.+)`, `(.+) not provided` → `YOCTO_NOTHING_PROVIDES:<pkg>`
- `dtc error`, `compilation failed` → `DTS_COMPILATION_ERROR`
- `critical (.+) cve` → `SECURITY_CRITICAL_CVE:<product>`
- ...and 20+ additional patterns across all four domains

**Canonical format:** `CATEGORY_TYPE:detail` (e.g., `BUILDROOT_MISSING_PACKAGE:openssl`)

**Consequences:**
- Positive: Multiple textual variations of the same error collapse into one canonical fingerprint
- Positive: PatternDB stores fewer, higher-quality entries
- Positive: Compression ratio is measurable via `NormalizationMetrics`
- Negative: Adding new patterns requires code changes to `normalizer.py`
- Negative: False normalization (different errors mapping to the same canonical) contaminates the knowledge base
- Negative: Fallback behavior can produce inconsistent canonical forms across runs

**Alternatives Rejected:**
- *Store raw fingerprints and use fuzzy matching at query time* — rejected because it's non-deterministic and un-auditable
- *LLM-based normalization* — rejected because it introduces non-determinism and external dependencies
- *No normalization* — rejected because it fragments learning below thresholds

**Implementation:** `titan/learning/normalizer.py:75` — `ErrorNormalizer` class. Called in `titan/learning/engine.py:149` (`_group_by_fingerprint`) and line 59 (`learn_from_run`).

---

## ADR-005: Recommendations Must Be Evidence-Based

**Status:** Accepted

**Context:** Early recommendation approaches returned raw pattern matches without evidence. Users (and automated consumers) had no way to assess whether a recommendation was reliable. A fix with 1 occurrence and 55% success rate looked the same as a fix with 100 occurrences and 95% success rate.

**Decision:** Every recommendation must include a complete evidence package:
- Occurrence count (how many times this error has been seen)
- Success rate (what fraction of fixes were accepted)
- Average score (mean validation score across all occurrences)
- Best fix (most frequently applied fix)
- Rank score (0-100 combining pattern quality, context, and feedback)
- Confidence (0.0-1.0 weighted score)

**Evidence format (from `titan/learning/recommender.py:53`):**
```
BuildrootError: BUILDROOT_MISSING_PACKAGE:openssl
  Ocorrências: 10
  Taxa de sucesso: 90.0%
  Score médio: 85.0/100
  Melhor fix: BR2_PACKAGE_OPENSSL=y
  Rank contextual: 78.5/100
  Confiança: 85%
```

**Consequences:**
- Positive: Users can assess recommendation quality at a glance
- Positive: Automated pipelines can set minimum confidence thresholds
- Positive: Confusion entries (mismatches) are visible for debugging
- Negative: More data to compute per recommendation
- Negative: Low-confidence recommendations are still returned (not filtered) — caller must decide threshold

**Alternatives Rejected:**
- *Return only best fix without evidence* — rejected because it hides reliability information
- *Filter out low-confidence recommendations* — rejected because the caller should decide the threshold
- *Probabilistic confidence (Bayesian)* — rejected because it adds complexity without clear benefit for deterministic patterns

**Implementation:** `titan/learning/recommender.py:32` — `recommend()` returns list of dicts with evidence fields. `RankingEngine.rank()` adds rank_score. `_confidence_score_raw()` computes confidence from weighted formula.

---

## ADR-006: FeedbackLoop Is Required for Continuous Learning

**Status:** Accepted

**Context:** The Learning Engine could learn patterns and make recommendations, but had no mechanism to know if the recommendations were actually applied or if they worked. Without this signal, the system could not distinguish between a fix that always works and a fix that only appears frequently because it's always wrong.

**Decision:** Every recommendation must be followed by a feedback record. The `FeedbackLoop` (`titan/learning/feedback.py`) records:

- What was recommended (`recommended_fix`)
- What was actually applied (`applied_fix`)
- Whether it worked (`accepted`)
- The validation score

This data feeds into the `RankingEngine` as the third signal component (0-30 points).

**Feedback schema:**
```
fingerprint: BUILDROOT_MISSING_PACKAGE:openssl
recommended_fix: BR2_PACKAGE_OPENSSL=y
applied_fix: BR2_PACKAGE_OPENSSL=y
accepted: True
score: 92.5
```

**Consequences:**
- Positive: Ranking engine improves over time as feedback accumulates
- Positive: `acceptance_rate()` and `best_fix()` per fingerprint become more accurate with more data
- Positive: Clear audit trail of what was recommended vs. what was actually done
- Negative: Feedback must be explicitly recorded — no automatic detection
- Negative: Cold start — no feedback data exists for new patterns

**Alternatives Rejected:**
- *Infer acceptance from validation score alone* — rejected because a fix can pass validation but not be applied
- *No feedback loop* — rejected because the ranking engine would be static and never improve
- *Feedback stored in PatternDB* — rejected because it mixes concern (aggregated stats vs. individual outcomes)

**Implementation:** `titan/learning/feedback.py:105` — `FeedbackLoop` class. `titan/learning/feedback.py:38` — `FeedbackDB` with SQLite `feedback_loop` table. Used by `RankingEngine._compute_rank()` at `ranking.py:66-67`.

---

## ADR-007: Validation Harness Is Mandatory for All Skill Execution

**Status:** Accepted

**Context:** Skills in Titan were initially free functions that could be called directly. There was no consistent way to measure quality, enforce contracts, or record outcomes. Each skill had ad-hoc validation logic (or none at all).

**Decision:** All skill execution MUST go through `ValidationHarness.execute()`. The harness:

1. Creates `SkillResult` from the skill's raw output
2. Selects a matching validator from the `REGISTRY` (list of `BaseValidator` subclasses)
3. Runs the validator, producing `ValidationResult` with weighted checks
4. Records the run in `ValidationHistory`
5. Returns both `SkillResult` and `ValidationResult`

**Validators required for all 4 skill types:**
| Skill | Validator | Key Checks |
|---|---|---|
| BuildrootSkill | BuildrootValidator | .config exists, output/images, rootfs, kernel, arch, toolchain |
| YoctoSkill | YoctoValidator | Workspace detected, recipes indexed, build dir exists |
| DTSSkill | DTSValidator | dtc compiles, no critical warnings, binding check, model detected |
| SecuritySkill | SecurityValidator | Scan completed, no critical CVEs, CVEs checked |

**Scoring formula:** weighted percentage of passed checks. Grade: ≥90 excellent, ≥75 good, ≥50 needs_review, <50 rejected.

**Consequences:**
- Positive: Every skill execution is measured and recorded
- Positive: New skills automatically get validation infrastructure
- Positive: Validators can be tested independently from skills
- Negative: Added boilerplate — each skill needs a validator class
- Negative: Validator REGISTRY must be manually maintained when adding new skills

**Alternatives Rejected:**
- *Skills call validators internally* — rejected because validators should be interchangeable and testable independently
- *Single generic validator* — rejected because each domain has fundamentally different success criteria
- *No validation* — rejected because it was the previous state and caused quality degradation

**Implementation:** `titan/validation/harness.py:16` — `ValidationHarness` class. `titan/validation/validators.py:8` — `BaseValidator` ABC + 4 concrete validators in `REGISTRY`. `titan/validation/score.py:13` — `Scorer.compute()` with weighted percentage.

---

## ADR-008: Learning Is Deterministic and Audit-Friendly

**Status:** Accepted

**Context:** As Titan added learning capabilities, there was pressure to use machine learning, fuzzy matching, or LLM-based approaches for pattern recognition and recommendation. This would make the system non-deterministic, un-auditable, and dependent on external services.

**Decision:** All learning, ranking, and recommendation is fully deterministic:

1. **Pattern extraction** — statistical aggregation only: count, mean, min, max. No ML models.
2. **Normalization** — compiled regex patterns only. No fuzzy string matching.
3. **Ranking** — weighted linear formula. No neural networks, no embeddings.
4. **Confidence** — weighted linear formula using only deterministic inputs (occurrences, score, rate).
5. **Feedback** — running averages of acceptance rates. No Bayesian inference.
6. **Metrics** — deterministic counters and ratios.

**Constants that control behavior:**
```python
MIN_OCCURRENCES = 3    # titan/learning/engine.py:13
MIN_SCORE = 60.0       # titan/learning/engine.py:14
MIN_SUCCESS_RATE = 0.60  # titan/learning/engine.py:15
```

**Consequences:**
- Positive: Every recommendation can be traced to specific data (which runs, which feedback records)
- Positive: No external dependencies for core learning logic
- Positive: Tests are fully deterministic — no flaky tests
- Positive: System produces identical output given identical input (debugging, replay)
- Negative: Cannot handle truly novel error patterns that don't match any regex
- Negative: No semantic similarity — "openssl" and "libssl" are different strings even though semantically related

**Alternatives Rejected:**
- *ML-based pattern extraction* — rejected because it violates determinism and auditability requirements
- *LLM for recommendation explanation* — rejected because explanations would not be reproducible
- *Bayesian confidence intervals* — rejected because it adds complexity without clear benefit for the deterministic use case

**Implementation:** Enforced across all learning modules: `titan/learning/normalizer.py` (regex only), `titan/learning/engine.py` (aggregation only), `titan/learning/ranking.py` (linear formula), `titan/learning/patterns.py` (deterministic SQLite schema).

---

## Appendix: Pending Decisions

### PENDING-001: Knowledge Engine ↔ Learning Engine Integration

**Status:** Not yet addressed — deferred to v13

**Context:** The Knowledge Engine (`titan/core/knowledge_engine.py`) and the Learning Engine (`titan/learning/`) currently operate independently. Knowledge records created by skills (`AutoFixSkill`, `DiagnosticEngine`) never reach PatternDB, and Learning Engine patterns never promote to KnowledgeEngine.

**Proposed approach:** Create a bridge that:
1. When `learn_all()` promotes a pattern, also create a `KnowledgeRecord` in KnowledgeEngine
2. When Knowledge Engine's `recognize_failure_patterns()` triggers, also suggest PatternDB patterns
3. Unify the feedback signal across both systems

**Current state:** Two independent databases — `.titan/knowledge.db` (KnowledgeEngine) and `.titan/patterns.db` (PatternDB).

### PENDING-002: Self-Tuning Thresholds

**Status:** Not yet addressed — deferred to v14

**Context:** `MIN_OCCURRENCES=3`, `MIN_SCORE=60.0`, and `MIN_SUCCESS_RATE=0.60` are hardcoded constants. With accumulating feedback data, the system could analyze whether these thresholds are optimal.

**Proposed approach:** Use `NormalizationMetrics` + `LearningBenchmark` results to suggest threshold adjustments. Track how many patterns would be promoted/lost at each threshold level.
