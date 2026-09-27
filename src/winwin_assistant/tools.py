"""Server-side handlers for the assistant's function tools."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date

from .catalog import Catalog
from .inventory import MockInventory, geo_features
from .state import SearchState, apply_patch


class ToolRouter:
    def __init__(self, catalog: Catalog, inventory: MockInventory, today: date):
        self.catalog = catalog
        self.inventory = inventory
        self.today = today

    def search_filter_catalog(self, args: dict) -> dict:
        return {"results": [
            {"phrase": q["phrase"], "candidates": self.catalog.search(q["phrase"], q.get("category_hint"))}
            for q in args["queries"]
        ]}

    def update_search(self, state: SearchState, args: dict) -> tuple[SearchState, dict]:
        res = apply_patch(state, args, self.catalog, self.today, geo_features)
        count = None if (res.missing_required or res.core_blocking) else self.inventory.count(res.state)
        payload = {
            "state": res.state.to_dict(),
            "applied": res.applied,
            "rejected": res.rejected,
            "issues": [asdict(i) for i in res.issues],
            "missing_required": res.missing_required,
            "offer_count": count,
            "relaxations": self.inventory.relaxations(res.state, previous=state) if count is not None and count < 5 else [],
            "facets": self.inventory.facets(res.state) if count else {},
        }
        return res.state, payload
