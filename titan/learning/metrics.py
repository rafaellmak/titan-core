from __future__ import annotations
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional

from .normalizer import ErrorNormalizer


class NormalizationMetrics:
    """Métricas sobre a qualidade do ErrorNormalizer.

    Mede compressão, colisão e fragmentação dos fingerprints.

    Colisão: dois erros com fix_signatures diferentes que o normalizador
    mapeia para o mesmo fingerprint canónico — isto CONTAMINA a base.

    Fragmentação: o mesmo raw fingerprint mapeado para canónicos
    diferentes em execuções distintas — isto FRAGMENTA o aprendizado.
    """

    def __init__(self, normalizer: Optional[ErrorNormalizer] = None):
        self.normalizer = normalizer or ErrorNormalizer()

    def compute(self, runs: List[dict]) -> Dict[str, Any]:
        raw_errors = [r.get("error_fingerprint", "") for r in runs if r.get("error_fingerprint")]
        total_raw = len(raw_errors)
        if total_raw == 0:
            return {
                "total_raw": 0,
                "unique_raw": 0,
                "unique_canonical": 0,
                "compression_ratio": 1.0,
                "categories": {},
                "top_fingerprints": [],
                "health": "no_data",
            }

        unique_raw = set(raw_errors)
        canonical_map: Dict[str, List[str]] = {}
        for r in runs:
            raw = r.get("error_fingerprint", "")
            cat = r.get("error_category", "")
            if raw:
                norm = self.normalizer.normalize(raw, cat)
                if norm not in canonical_map:
                    canonical_map[norm] = []
                canonical_map[norm].append(raw)

        unique_canonical = set(canonical_map.keys())
        compression_ratio = round(len(unique_raw) / max(len(unique_canonical), 1), 2)

        cat_counts: Dict[str, int] = {}
        for r in runs:
            cat = r.get("error_category", "GenericError")
            cat_counts[cat] = cat_counts.get(cat, 0) + 1

        canonical_counter = Counter({
            k: len(v) for k, v in canonical_map.items()
        })
        top_fps = [
            {"fingerprint": k, "occurrences": v}
            for k, v in canonical_counter.most_common(10)
        ]

        collisions = self._detect_collisions(runs)
        fragments = self._detect_fragmentation(runs, canonical_map)

        health = "healthy"
        if collisions:
            health = "collisions_detected"
        if fragments and health == "healthy":
            health = "fragmentation_detected"
        if collisions and fragments:
            health = "collisions_and_fragmentation"

        return {
            "total_raw": total_raw,
            "unique_raw": len(unique_raw),
            "unique_canonical": len(unique_canonical),
            "compression_ratio": compression_ratio,
            "categories": dict(sorted(cat_counts.items(), key=lambda x: -x[1])),
            "top_fingerprints": top_fps,
            "collisions": collisions,
            "collision_count": len(collisions),
            "fragmentation": fragments,
            "fragmentation_count": len(fragments),
            "health": health,
        }

    def summarize(self, runs: List[dict]) -> str:
        m = self.compute(runs)
        lines = [
            "=" * 50,
            "NormalizationMetrics",
            "=" * 50,
            f"  Raw Errors:       {m['total_raw']}",
            f"  Unique Raw:       {m['unique_raw']}",
            f"  Unique Canonical: {m['unique_canonical']}",
            f"  Compression Ratio: {m['compression_ratio']}x",
            f"  Health:           {m['health']}",
            "",
            "Top Fingerprints:",
        ]
        for fp in m["top_fingerprints"]:
            lines.append(f"  {fp['fingerprint']:<50s} {fp['occurrences']}")

        if m["collisions"]:
            lines.append("")
            lines.append("Collisions (fix → canonical):")
            for norm, fixes in m["collisions"][:5]:
                lines.append(f"  {norm}")
                for f in fixes:
                    lines.append(f"    ← fix: {f}")

        if m["fragmentation"]:
            lines.append("")
            lines.append("Fragmentation (same raw → different canonical):")
            for raw, norms in m["fragmentation"][:5]:
                lines.append(f"  {raw}")
                for n in norms:
                    lines.append(f"    → {n}")

        lines.append("")
        return "\n".join(lines)

    def _detect_collisions(self, runs: List[dict]) -> List[tuple]:
        """Colisão: fix_signatures diferentes → mesmo fingerprint canónico."""
        norm_fixes: Dict[str, set] = defaultdict(set)
        for r in runs:
            norm = self.normalizer.normalize(
                r.get("error_fingerprint", ""),
                r.get("error_category", ""),
            )
            fix = r.get("fix_signature", "").strip()
            if fix:
                norm_fixes[norm].add(fix)

        collisions = [
            (norm, sorted(fixes))
            for norm, fixes in norm_fixes.items()
            if len(fixes) > 1
        ]
        collisions.sort(key=lambda x: -len(x[1]))
        return collisions

    def _detect_fragmentation(self, runs: List[dict],
                              canonical_map: Dict[str, List[str]]) -> List[tuple]:
        """Fragmentação: mesmo raw fingerprint → canónicos diferentes."""
        raw_to_norms: Dict[str, set] = {}
        for r in runs:
            raw = r.get("error_fingerprint", "")
            if not raw:
                continue
            norm = self.normalizer.normalize(raw, r.get("error_category", ""))
            if raw not in raw_to_norms:
                raw_to_norms[raw] = set()
            raw_to_norms[raw].add(norm)
        fragments = [
            (raw, sorted(norms))
            for raw, norms in raw_to_norms.items()
            if len(norms) > 1
        ]
        fragments.sort(key=lambda x: -len(x[1]))
        return fragments
