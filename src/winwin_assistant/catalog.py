"""Filter catalog loading and lookup (backs the `search_filter_catalog` tool)."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parents[2] / "filters" / "catalog.json"
_STOP = {"a", "an", "the", "with", "and", "or", "of", "in", "on", "to", "for", "i", "is", "be", "some", "real", "good"}


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9²]+", text.lower()) if t not in _STOP}


class Catalog:
    def __init__(self, filters: list[dict]):
        self.filters = filters
        self.by_id = {f["id"]: f for f in filters}
        self.groups: dict[str, list[str]] = {}
        for f in filters:
            if g := f.get("exclusive_group"):
                self.groups.setdefault(g, []).append(f["id"])

    def get(self, filter_id: str) -> dict | None:
        return self.by_id.get(filter_id)

    def conflicts(self, a: str, b: str) -> bool:
        fa, fb = self.by_id[a], self.by_id[b]
        if b in fa.get("conflicts_with", []):
            return True
        g = fa.get("exclusive_group")
        return bool(g) and g == fb.get("exclusive_group") and a != b

    def soft_conflicts(self, a: str, b: str) -> bool:
        return b in self.by_id[a].get("soft_conflicts_with", [])

    def search(self, phrase: str, category_hint: str | None = None, limit: int = 5) -> list[dict]:
        """Cheap lexical search. Production would use embeddings (label + synonyms) in a vector store,
        but the contract is identical: phrase in, ranked filter candidates out."""
        q = _tokens(phrase)
        scored = []
        for f in self.filters:
            if category_hint and f["category"] != category_hint:
                continue
            best_syn = max((len(q & _tokens(s)) / max(len(_tokens(s)), 1) for s in f["synonyms"]), default=0)
            exact_syn = any(s.lower() in phrase.lower() for s in f["synonyms"])
            label = len(q & _tokens(f["label"])) / max(len(_tokens(f["label"])), 1)
            score = max(best_syn, label) + (0.5 if exact_syn else 0)
            if score > 0.3:
                scored.append((score, f))
        scored.sort(key=lambda x: -x[0])
        return [
            {k: f[k] for k in ("id", "label", "type", "unit", "min", "max", "options") if k in f} | {"score": round(s, 2)}
            for s, f in scored[:limit]
        ]


@lru_cache(maxsize=1)
def load_catalog(path: Path = CATALOG_PATH) -> Catalog:
    return Catalog(json.loads(path.read_text())["filters"])
