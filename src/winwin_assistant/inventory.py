"""Mock inventory service: offer counts, relaxation suggestions and facets.

In production this is the real availability backend (a cheap `count` endpoint over cached
rates). The assistant only ever repeats numbers returned from here. The mock is deterministic
so examples and tests are reproducible.
"""

from __future__ import annotations

import zlib
from datetime import date, timedelta

from .catalog import Catalog
from .state import SearchState

DESTINATIONS = {
    # name -> (hotels with availability on an average night, geo features)
    "haarlem": (260, {"canals", "river"}),
    "amsterdam": (920, {"canals", "river"}),
    "prague": (1100, {"river"}),
    "barcelona": (1500, {"coast", "mountains"}),
    "chamonix": (160, {"mountains", "ski_area", "river"}),
    "anywhere": (250000, {"coast", "canals", "river", "lake", "mountains", "ski_area", "desert", "volcano", "aurora_zone"}),
}


def geo_features(name: str) -> set[str] | None:
    entry = DESTINATIONS.get(name.lower())
    return entry[1] if entry else None


def _selectivity(fid: str, entry: dict) -> float:
    """Share of hotels that satisfy a filter (deterministic pseudo-random 0.45..0.97)."""
    base = 0.45 + (zlib.crc32(fid.encode()) % 53) / 100
    if entry.get("bool") is False:
        return min(0.98, 1.15 - base)
    if "min" in entry:
        width = (entry.get("max") or 0) - (entry.get("min") or 0)
        return base if width <= 0 else min(0.95, base + 0.1)
    return base


def _safe_to_relax(fid: str) -> bool:
    """Do not propose dropping needs tied to safety, access, children or animals."""
    category = fid.split(".", 1)[0]
    if category in {"accessibility", "pets", "family", "safety"}:
        return False
    return not any(word in fid for word in ("allerg", "smok", "child", "baby", "crib", "wheelchair"))


class MockInventory:
    def __init__(self, catalog: Catalog):
        self.catalog = catalog

    def count(self, s: SearchState) -> int | None:
        if not (s.destination and s.dates and s.dates.get("check_in") and s.guests):
            return None
        base, _ = DESTINATIONS.get(s.destination["name"].lower(), (300, set()))
        seasonal = 0.7 if date.fromisoformat(s.dates["check_in"]).month in (7, 8) else 0.8
        n = base * seasonal * (0.9 if s.guests["adults"] + len(s.guests["children_ages"]) > 2 else 1.0)
        for fid, entry in s.filters.items():
            if entry["importance"] == "must":
                n *= _selectivity(fid, entry)
        return int(n)

    def _label(self, fid: str, entry: dict) -> str:
        label = self.catalog.get(fid)["label"]
        return f"no {label.lower()}" if entry.get("bool") is False else label

    def relaxations(self, s: SearchState, previous: SearchState | None = None, limit: int = 3) -> list[dict]:
        """Cheapest changes that increase the count, best first. Never applied automatically."""
        current = self.count(s)
        if current is None:
            return []
        musts = [fid for fid, e in s.filters.items() if e["importance"] == "must" and _safe_to_relax(fid)]

        def without(*fids: str) -> SearchState:
            trial = SearchState.from_dict(s.to_dict())
            for f in fids:
                trial.filters.pop(f)
            return trial

        options = [{"change": f"remove '{self._label(f, s.filters[f])}'", "remove": [f],
                    "new_count": self.count(without(f)), "priority": 2} for f in musts]
        for shift in (-1, 1):
            trial = SearchState.from_dict(s.to_dict())
            ci = date.fromisoformat(s.dates["check_in"]) + timedelta(days=shift)
            co = date.fromisoformat(s.dates["check_out"]) + timedelta(days=shift)
            trial.dates = s.dates | {"check_in": ci.isoformat(), "check_out": co.isoformat()}
            # shoulder days are usually a bit less busy
            options.append({"change": f"shift dates to {ci:%d %b}–{co:%d %b %Y}", "remove": [],
                            "new_count": self.count(trial), "priority": 3})
        if not any(o["new_count"] > current for o in options):
            # no single change helps -> try pairs
            for i, a in enumerate(musts):
                for b in musts[i + 1:]:
                    options.append({"change": f"remove '{self._label(a, s.filters[a])}' and "
                                              f"'{self._label(b, s.filters[b])}'",
                                    "remove": [a, b], "new_count": self.count(without(a, b)), "priority": 4})
        if previous is not None and current == 0:
            # the most intuitive fix for "my last message killed all results"
            added = [f for f in s.filters if f not in previous.filters and _safe_to_relax(f)]
            if added:
                labels = ", ".join(self._label(f, s.filters[f]) for f in added)
                demoted = SearchState.from_dict(s.to_dict())
                for f in added:
                    demoted.filters[f]["importance"] = "nice_to_have"
                options.append({"change": f"keep {labels} as nice-to-have (ranked first, not required)",
                                "remove": [], "demote": added, "new_count": self.count(demoted), "priority": 0})
                options.append({"change": f"undo the last change ({labels})",
                                "remove": added, "new_count": self.count(without(*added)), "priority": 1})
        if not any((o["new_count"] or 0) > current for o in options) and musts:
            # Very narrow searches may need more than two convenience filters relaxed.
            ranked = sorted(musts, key=lambda f: _selectivity(f, s.filters[f]))
            for n in range(3, len(ranked) + 1):
                removed = ranked[:n]
                new_count = self.count(without(*removed))
                if new_count and new_count > current:
                    options.append({"change": f"remove {n} optional constraints", "remove": removed,
                                    "new_count": new_count, "priority": 5})
                    break
        options = [o for o in options if (o["new_count"] or 0) > current]
        options.sort(key=lambda o: (o["priority"], -o["new_count"]))
        return [{k: v for k, v in o.items() if k != "priority"} for o in options[:limit]]

    def facets(self, s: SearchState) -> dict:
        n = self.count(s) or 0
        return {"price_per_night_eur": {"<100": int(n * .18), "100-150": int(n * .31), "150-250": int(n * .34),
                                        ">250": n - int(n * .18) - int(n * .31) - int(n * .34)}}
