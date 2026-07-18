"""Learning Validation Phase — otimizado para performance."""
import json, sys, tempfile, time
from pathlib import Path
from datetime import datetime
from collections import Counter
from typing import Any, Dict, List

from titan.validation.persistence import ValidationDB
from titan.validation.history import ValidationHistory
from titan.learning.patterns import PatternDB
from titan.learning.normalizer import ErrorNormalizer
from titan.learning.context import PatternContextDB
from titan.learning.feedback import FeedbackLoop, FeedbackDB
from titan.learning.engine import LearningEngine
from titan.learning.recommender import Recommender
from titan.learning.replay import ReplayRunner
from titan.learning.metrics import NormalizationMetrics
from titan.learning.dataset import SyntheticDataset

N_TRAIN = 2000
N_TEST = 500
PER_CATEGORY = ["BuildrootError", "YoctoError", "DTSError", "SecurityError"]
GROWTH_POINTS = [0, 25, 50, 75, 100]
SEED = 42


def seed_history(db_path: str, events: list) -> ValidationHistory:
    vdb = ValidationDB(db_path=db_path)
    history = ValidationHistory(db=vdb)
    for e in events:
        vdb.insert_run({
            "skill_name": e.get("skill_name", "BuildrootSkill"),
            "score": e.get("score", 80.0),
            "accepted": 1 if e.get("accepted", True) else 0,
            "error_category": e.get("error_category", "BuildrootError"),
            "error_fingerprint": e.get("error_fingerprint", "missing openssl"),
            "fix_signature": e.get("fix_signature", ""),
            "timestamp": e.get("timestamp", datetime.now().isoformat()),
            "summary": e.get("summary", ""),
            "raw_data": e.get("raw_data", "{}"),
            "metadata": e.get("metadata", "{}"),
        })
    return history


def run_benchmark_on(tmp_base: str, train: list, test: list) -> Dict:
    history = seed_history(f"{tmp_base}/val.db", train)
    test_history = seed_history(f"{tmp_base}/test.db", test)

    engine = LearningEngine(
        history,
        db=PatternDB(db_path=Path(tmp_base) / "patterns.db"),
        normalizer=ErrorNormalizer(),
        context_db=PatternContextDB(db_path=Path(tmp_base) / "ctx.db"),
        feedback=FeedbackLoop(FeedbackDB(db_path=Path(tmp_base) / "fb.db")),
    )

    runner = ReplayRunner(test_history, engine=engine)
    summary = runner.replay()

    recs = summary.get("with_recommendation", 0)
    top1 = summary.get("top1_matches", 0)
    total = summary.get("total_runs", 0)
    empty = summary.get("empty_recommendations", 0)
    top3 = summary.get("top3_matches", 0)

    precision = round(top1 / recs, 4) if recs > 0 else 0.0
    frr = round((recs - top1) / recs, 4) if recs > 0 else 0.0
    score = round(
        summary.get("top1_accuracy", 0) * 0.5
        + summary.get("top3_accuracy", 0) * 0.3
        + summary.get("recommendation_recall", 0) * 0.2, 4
    )

    cats = runner.replay_by_category()
    failures = [r for r in runner.results if r.get("top1_fix") and not r.get("is_match")]

    return {
        "summary": {
            **summary,
            "precision": precision,
            "false_recommendation_rate": frr,
            "learning_score": score,
        },
        "categories": cats,
        "failures": failures,
    }


def main():
    t0 = time.time()
    ds = SyntheticDataset(seed=SEED)

    def p(msg=""):
        print(msg, flush=True)

    p("=" * 70)
    p("  LEARNING VALIDATION PHASE")
    p("=" * 70)
    p()
    p(f"  Dataset: {N_TRAIN} treino + {N_TEST} teste = {N_TRAIN+N_TEST} eventos")
    p(f"  Categorias: {', '.join(PER_CATEGORY)}")
    p()

    p("  Gerando dataset sintético...")
    all_events = ds.generate(n_events=N_TRAIN + N_TEST, accepted_rate=0.75)
    train_events = all_events[:N_TRAIN]
    test_events = all_events[N_TRAIN:N_TRAIN + N_TEST]
    p(f"  OK — {len(all_events)} eventos gerados")
    p()

    # 1. Growth analysis
    p("─" * 70)
    p("  1. CURVAS DE APRENDIZADO")
    p("─" * 70)
    p()
    p(f"  {'%':>5s}  {'Casos':>6s}  {'Top-1':>8s}  {'Top-3':>8s}  "
      f"{'Recall':>7s}  {'Precisão':>8s}  {'FRR':>7s}  {'Score':>7s}")
    p("  " + "-" * 68)

    growth_data = []
    for pct in GROWTH_POINTS:
        n = int(len(train_events) * pct / 100)
        subset = train_events[:n]
        tmp = tempfile.mkdtemp()
        result = run_benchmark_on(tmp, subset, test_events)
        s = result["summary"]
        growth_data.append(result)

        p(f"  {pct:>4d}%  {n:>6d}  "
          f"{s['top1_accuracy']:>7.1%}  {s['top3_accuracy']:>7.1%}  "
          f"{s['recommendation_recall']:>7.1%}  {s['precision']:>7.1%}  "
          f"{s['false_recommendation_rate']:>7.1%}  {s['learning_score']:>6.2f}")

    fs = growth_data[-1]["summary"]
    delta = growth_data[-1]["summary"]["top1_accuracy"] - growth_data[0]["summary"]["top1_accuracy"]
    p()
    p(f"  Variação Top-1 (0% → 100%): {delta:+.1%}")
    p()

    # 2. Normalization quality
    p("─" * 70)
    p("  2. QUALIDADE DE NORMALIZAÇÃO")
    p("─" * 70)
    p()
    nm = NormalizationMetrics(ErrorNormalizer()).compute(train_events)
    p(f"  Erros brutos:              {nm['total_raw']}")
    p(f"  Fingerprints raw:          {nm['unique_raw']}")
    p(f"  Fingerprints canónicos:    {nm['unique_canonical']}")
    p(f"  Compression Ratio:         {nm['compression_ratio']}x")
    p(f"  Colisões:                  {nm['collision_count']}")
    p(f"  Fragmentações:             {nm['fragmentation_count']}")
    p(f"  Saúde:                     {nm['health']}")
    p()

    if nm["top_fingerprints"]:
        p("  Top Fingerprints (ocorrências):")
        for fp in nm["top_fingerprints"][:6]:
            p(f"    {fp['fingerprint']:<55s} {fp['occurrences']}")
        p()

    if nm["collisions"]:
        p("  Piores colisões (fixes diferentes → mesmo canónico):")
        for norm_fp, fixes in nm["collisions"][:5]:
            p(f"    {norm_fp}")
            for f in fixes[:3]:
                p(f"      ← fix: {f}")
        p()

    if nm["fragmentation"]:
        p("  Piores fragmentações (mesmo raw → canónicos diferentes):")
        for raw, norms in nm["fragmentation"][:5]:
            p(f"    '{raw}'")
            for n in norms:
                p(f"      → {n}")
        p()

    # 3. Category breakdown
    p("─" * 70)
    p("  3. BREAKDOWN POR CATEGORIA")
    p("─" * 70)
    p()
    cats = growth_data[-1]["categories"]
    p(f"  {'Categoria':<20s}  {'Total':>6s}  {'Top-1':>8s}  {'Top-3':>8s}")
    p("  " + "-" * 48)

    best_cat, worst_cat = "", ""
    best_acc, worst_acc = -1.0, 2.0
    for cat in sorted(cats.keys()):
        d = cats[cat]
        t1 = d.get("top1_accuracy", 0)
        p(f"  {cat:<20s}  {d['total']:>6d}  {t1:>7.1%}  {d.get('top3_accuracy', 0):>7.1%}")
        if d["total"] > 0:
            if t1 > best_acc:
                best_acc, best_cat = t1, cat
            if t1 < worst_acc:
                worst_acc, worst_cat = t1, cat

    p()
    p(f"  Categoria mais forte:  {best_cat} (Top-1: {best_acc:.1%})")
    p(f"  Categoria mais fraca:  {worst_cat} (Top-1: {worst_acc:.1%})")
    p()

    # 4. Failure analysis
    p("─" * 70)
    p("  4. ANÁLISE DE FALHAS")
    p("─" * 70)
    p()
    failures = growth_data[-1]["failures"]
    p(f"  Total de falhas (recomendou mas errou): {len(failures)}")
    if failures:
        p()
        p(f"  {'#':>3s}  {'Fingerprint':<35s}  {'Fix Esperado':<28s}  "
          f"{'Fix Recomendado':<28s}  {'Rank':>6s}")
        p("  " + "-" * 105)
        for i, f in enumerate(failures[:15]):
            p(f"  {i+1:>3d}  {f['fingerprint']:<35s}  {f['actual_fix']:<28s}  "
              f"{f['top1_fix']:<28s}  {f.get('rank_score', 1):>5.0f}")

        if len(failures) > 15:
            p(f"  ... e mais {len(failures) - 15} falhas")

        # Group
        fp_counts = Counter()
        for f in failures:
            fp_counts[f"{f['category']}:{f['fingerprint']}"] += 1
        p()
        p("  Falhas por padrão de erro:")
        for key, count in fp_counts.most_common(5):
            p(f"    {key:<60s} {count} falhas")
    p()

    # 5. Conclusion
    p("=" * 70)
    p("  5. CONCLUSÃO")
    p("=" * 70)
    p()

    top1 = fs["top1_accuracy"]
    top3 = fs["top3_accuracy"]
    recall = fs["recommendation_recall"]
    score = fs["learning_score"]
    precision = fs["precision"]
    frr_val = fs["false_recommendation_rate"]
    empty = fs["empty_recommendations"]
    total = fs["total_runs"]
    col_rate = nm["collision_count"] / max(nm["unique_canonical"], 1)
    frag_rate = nm["fragmentation_count"] / max(nm["unique_raw"], 1)

    p(f"  A. O Titan melhora com experiência?")
    if delta > 0.05:
        p(f"     SIM — Top-1 subiu {delta:+.1%} com mais dados de treino.")
    elif delta > 0.01:
        p(f"     PARCIALMENTE — Top-1 variou {delta:+.1%}.")
    else:
        p(f"     NÃO SIGNIFICATIVAMENTE — Top-1 variou {delta:+.1%}.")
    p()

    p(f"  B. Quais subsistemas contribuem mais?")
    p(f"     Categoria mais forte:  {best_cat} ({best_acc:.1%})")
    p(f"     Categoria mais fraca:  {worst_cat} ({worst_acc:.1%})")
    p(f"     Normalizer: {nm['compression_ratio']}x compressão, "
      f"{nm['collision_count']} colisões, {nm['fragmentation_count']} fragmentações")
    p()

    p(f"  C. Qual subsistema é atualmente o gargalo?")
    btln = []
    if precision < 0.7:
        btln.append(f"Precisão ({precision:.1%}) — muitas recomendações erradas")
    if recall < 0.7:
        btln.append(f"Recall ({recall:.1%}) — muitas não-recomendações")
    if col_rate > 0.05:
        btln.append(f"Collision rate ({col_rate:.1%}) — fingerprints contaminados")
    if frag_rate > 0.02:
        btln.append(f"Fragmentation rate ({frag_rate:.1%})")
    if empty > total * 0.3:
        btln.append(f"Não-recomendações ({empty}/{total}) — padrões insuficientes")
    if not btln:
        btln.append("Nenhum gargalo crítico nos dados atuais")
    for b in btln:
        p(f"     • {b}")
    p()

    p(f"  D. O que deve ser melhorado a seguir?")
    recs = []
    if recall < 0.8:
        recs.append(f"Expandir normalizador ({nm['unique_canonical']} canónicos para "
                    f"{nm['unique_raw']} fingerprints raw)")
    if precision < 0.8:
        recs.append(f"Reduzir FRR ({frr_val:.1%}) — revisar colisões de fingerprint")
    if col_rate > 0.05:
        recs.append(f"Resolver {nm['collision_count']} colisões no normalizador")
    if frag_rate > 0.02:
        recs.append(f"Resolver {nm['fragmentation_count']} fragmentações")

    recs.append(f"Executar benchmark com dados reais de workspace "
                f"(Score={score:.2f}, Top-1={top1:.1%}, Top-3={top3:.1%}, "
                f"Precisão={precision:.1%})")

    for i, r in enumerate(recs, 1):
        p(f"     {i}. {r}")
    p()

    # Summary block
    grade = "A" if score >= 0.9 else "B" if score >= 0.75 else "C" if score >= 0.60 else "D" if score >= 0.40 else "F"
    p("─" * 70)
    p("  RESUMO DE MÉTRICAS")
    p("─" * 70)
    p()
    p(f"  Dataset:           {N_TRAIN} treino + {N_TEST} teste")
    p(f"  Top-1 Accuracy:    {top1:.1%}")
    p(f"  Top-3 Accuracy:    {top3:.1%}")
    p(f"  Recall:            {recall:.1%}")
    p(f"  Precisão:          {precision:.1%}")
    p(f"  FRR:               {frr_val:.1%}")
    p(f"  Learning Score:    {score:.2f}")
    p(f"  Grade:             {grade}")
    p(f"  Compression:       {nm['compression_ratio']}x")
    p(f"  Collision Rate:    {col_rate:.1%} ({nm['collision_count']})")
    p(f"  Fragmentation Rate:{frag_rate:.1%} ({nm['fragmentation_count']})")
    p()
    p(f"  Tempo total:       {time.time() - t0:.1f}s")
    p()

    # Save JSON
    growth_save = []
    for pct, gd in zip(GROWTH_POINTS, growth_data):
        s = gd["summary"]
        growth_save.append({
            "pct": pct, "cases": int(N_TRAIN * pct / 100),
            "top1": s["top1_accuracy"], "top3": s["top3_accuracy"],
            "recall": s["recommendation_recall"],
            "precision": s["precision"], "frr": s["false_recommendation_rate"],
            "score": s["learning_score"],
            "matches": s["top1_matches"], "empty": s["empty_recommendations"],
        })

    with open("/tmp/learning_benchmark_results.json", "w") as f:
        json.dump({
            "growth": growth_save,
            "normalization": {
                "total_raw": nm["total_raw"],
                "unique_raw": nm["unique_raw"],
                "unique_canonical": nm["unique_canonical"],
                "compression_ratio": nm["compression_ratio"],
                "collision_count": nm["collision_count"],
                "fragmentation_count": nm["fragmentation_count"],
                "health": nm["health"],
                "top_fingerprints": nm["top_fingerprints"],
                "collisions": [[str(x) for x in c] for c in nm["collisions"][:5]],
                "fragmentation": [[str(x) for x in f] for f in nm["fragmentation"][:5]],
            },
            "final_summary": {
                "top1_accuracy": top1,
                "top3_accuracy": top3,
                "recall": recall,
                "precision": precision,
                "false_recommendation_rate": frr_val,
                "learning_score": score,
                "grade": grade,
            },
            "categories": {cat: d for cat, d in cats.items()},
            "failures_count": len(failures),
            "failures_sample": [{
                "fingerprint": f["fingerprint"],
                "actual_fix": f["actual_fix"],
                "top1_fix": f["top1_fix"],
                "category": f["category"],
            } for f in failures[:20]],
        }, f, indent=2)


if __name__ == "__main__":
    main()
