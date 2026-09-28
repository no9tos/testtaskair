"""Search state + deterministic patch validation.

The LLM *proposes* a patch (the `update_search` tool call); this module *disposes*:
it validates core slots, filter ids/values, resolves conflicts and produces machine-readable
`issues` the model turns into a friendly reply. Nothing the model says reaches the search
backend without passing through here.
"""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Callable

from .catalog import Catalog

MAX_NIGHTS = 30
MAX_DAYS_AHEAD = 500
MAX_GUESTS_PER_ROOM = 4
CORE_ISSUE_CODES = {"destination_empty", "destination_ambiguous", "dates_order", "dates_past", "stay_too_long",
                    "dates_too_far", "dates_incomplete", "dates_invalid", "no_adult", "rooms_invalid",
                    "rooms_exceed_adults", "children_ages_missing", "children_ages_invalid"}


@dataclass
class Issue:
    severity: str  # blocking | warning | info
    code: str
    message: str
    filters: list[str] = field(default_factory=list)


@dataclass
class SearchState:
    destination: dict | None = None
    dates: dict | None = None
    guests: dict | None = None
    filters: dict[str, dict] = field(default_factory=dict)  # id -> {value..., importance, source_quote}
    unmapped_preferences: list[str] = field(default_factory=list)
    sort: str = "recommended"
    currency: str = "EUR"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict | None) -> "SearchState":
        return cls(**d) if d else cls()


@dataclass
class PatchResult:
    state: SearchState
    applied: list[str]
    rejected: list[dict]
    issues: list[Issue]
    missing_required: list[str]

    @property
    def blocking(self) -> bool:
        """Something needs the user's decision before the search is final."""
        return any(i.severity == "blocking" for i in self.issues)

    @property
    def core_blocking(self) -> bool:
        """A destination / dates / guests problem: counting now would describe a search the user did not ask for.
        (Filter contradictions do not block counting: the conflicting filters simply were not applied.)"""
        return any(i.severity == "blocking" and i.code in CORE_ISSUE_CODES for i in self.issues)


GeoLookup = Callable[[str], set[str] | None]  # destination name -> geo features ({"coast","canals",...}) or None


def apply_patch(state: SearchState, patch: dict, catalog: Catalog, today: date,
                geo_features: GeoLookup = lambda _: None) -> PatchResult:
    new = SearchState(currency=state.currency) if patch.get("reset") else copy.deepcopy(state)
    issues: list[Issue] = []
    applied: list[str] = []
    rejected: list[dict] = []

    _apply_destination(new, patch["destination"], issues)
    _apply_dates(new, patch["dates"], today, issues)
    _apply_guests(new, patch["guests"], issues)
    requested_currency = patch.get("currency")
    if requested_currency and requested_currency != "EUR":
        issues.append(Issue("blocking", "currency_conversion_unavailable",
                            f"This demo stores monetary filters in EUR; confirm a EUR amount for {requested_currency} budgets."))
    elif requested_currency:
        new.currency = requested_currency
    if patch.get("sort") and patch["sort"] != "keep":
        new.sort = patch["sort"]
    for pref in patch.get("unmapped_preferences", []):
        if pref not in new.unmapped_preferences:
            new.unmapped_preferences.append(pref)

    features = geo_features(new.destination["name"]) if new.destination else None
    _apply_filters(new, patch.get("filter_operations", []), catalog, features, issues, applied, rejected,
                   unsupported_currency=bool(requested_currency and requested_currency != "EUR"))
    _plausibility(new, issues)

    missing = []
    if not new.destination:
        missing.append("destination")
    if not new.dates or not (new.dates.get("check_in") and new.dates.get("check_out")):
        missing.append("dates")
    if not new.guests or not new.guests.get("adults"):
        missing.append("guests")
    elif any(a < 0 for a in new.guests.get("children_ages") or []):
        missing.append("children_ages")
    return PatchResult(new, applied, rejected, issues, missing)


# --------------------------------------------------------------------------- core slots
def _apply_destination(s: SearchState, d: dict, issues: list[Issue]) -> None:
    if d["action"] == "clear":
        s.destination = None
    elif d["action"] == "set":
        if not d.get("name"):
            issues.append(Issue("blocking", "destination_empty", "Destination was set without a name."))
            return
        if d.get("ambiguous_with"):
            issues.append(Issue("blocking", "destination_ambiguous",
                                f"'{d['name']}' is ambiguous: also {', '.join(d['ambiguous_with'])}."))
            s.destination = None
            return
        s.destination = {k: d.get(k) for k in ("name", "type", "country_code")}


def _apply_dates(s: SearchState, d: dict, today: date, issues: list[Issue]) -> None:
    if d["action"] == "clear":
        s.dates = None
        return
    if d["action"] != "set":
        return
    ci, co = d.get("check_in"), d.get("check_out")
    if ci and co:
        try:
            ci_d, co_d = date.fromisoformat(ci), date.fromisoformat(co)
        except (TypeError, ValueError):
            issues.append(Issue("blocking", "dates_invalid", "Check-in and check-out must be valid calendar dates."))
            return
        if co_d <= ci_d:
            issues.append(Issue("blocking", "dates_order", f"Check-out {co} is not after check-in {ci}."))
            return
        if ci_d < today:
            issues.append(Issue("blocking", "dates_past", f"Check-in {ci} is in the past (today is {today})."))
            return
        if (co_d - ci_d).days > MAX_NIGHTS:
            issues.append(Issue("blocking", "stay_too_long", f"Stays are limited to {MAX_NIGHTS} nights."))
            return
        if (ci_d - today).days > MAX_DAYS_AHEAD:
            issues.append(Issue("blocking", "dates_too_far", "Hotels do not sell rooms this far ahead yet."))
            return
        s.dates = {"check_in": ci, "check_out": co, "nights": (co_d - ci_d).days,
                   "flexibility": d.get("flexibility", "exact")}
    elif ci or co:
        issues.append(Issue("blocking", "dates_incomplete", "Only one of check-in / check-out was given."))
        return
    else:  # vague window, e.g. "in May"
        ws, we = d.get("window_start"), d.get("window_end")
        if not ws or not we:
            issues.append(Issue("blocking", "dates_incomplete", "A flexible date window needs both a start and an end."))
            return
        try:
            ws_d, we_d = date.fromisoformat(ws), date.fromisoformat(we)
        except (TypeError, ValueError):
            issues.append(Issue("blocking", "dates_invalid", "The date window must contain valid calendar dates."))
            return
        if we_d < ws_d:
            issues.append(Issue("blocking", "dates_order", "The date window ends before it begins."))
            return
        if ws_d < today:
            issues.append(Issue("blocking", "dates_past", f"Window starting {ws} is in the past."))
            return
        if (ws_d - today).days > MAX_DAYS_AHEAD:
            issues.append(Issue("blocking", "dates_too_far", "Hotels do not sell rooms this far ahead yet."))
            return
        nights = d.get("nights")
        if nights is not None and (not isinstance(nights, int) or not 1 <= nights <= MAX_NIGHTS):
            issues.append(Issue("blocking", "dates_invalid", f"Stay length must be 1–{MAX_NIGHTS} nights."))
            return
        s.dates = {"check_in": None, "check_out": None, "window_start": ws, "window_end": we,
                   "nights": nights, "flexibility": d.get("flexibility", "unknown")}
    if d.get("assumption"):
        issues.append(Issue("info", "dates_assumption", d["assumption"]))


def _apply_guests(s: SearchState, g: dict, issues: list[Issue]) -> None:
    if g["action"] == "clear":
        s.guests = None
        return
    if g["action"] != "set":
        return
    adults, kids = g.get("adults"), g.get("children_ages") or []
    rooms = g.get("rooms")
    if not isinstance(adults, int) or isinstance(adults, bool) or adults < 1:
        issues.append(Issue("blocking", "no_adult", "At least one adult is required per booking."))
        return
    if not isinstance(rooms, int) or isinstance(rooms, bool) or rooms < 1:
        issues.append(Issue("blocking", "rooms_invalid", "The number of rooms must be at least one."))
        return
    if any(not isinstance(a, int) or isinstance(a, bool) or a < -1 for a in kids):
        issues.append(Issue("blocking", "children_ages_invalid", "Child ages must be 0–17, or unknown (-1)."))
        return
    if any(a > 17 for a in kids):
        issues.append(Issue("warning", "child_age_adult", "A 'child' aged 18+ is counted as an adult."))
        adults += sum(1 for a in kids if a > 17)
        kids = [a for a in kids if a <= 17]
    if rooms > adults:
        issues.append(Issue("blocking", "rooms_exceed_adults", "Each room needs at least one adult."))
        return
    if (adults + len(kids)) / rooms > MAX_GUESTS_PER_ROOM:
        issues.append(Issue("warning", "crowded_rooms",
                            f"{adults + len(kids)} guests in {rooms} room(s) – few hotels allow that; consider more rooms."))
    if any(a < 0 for a in kids):
        issues.append(Issue("blocking", "children_ages_missing", "Children ages are needed for correct prices."))
    s.guests = {"adults": adults, "children_ages": kids, "rooms": rooms}
    if g.get("assumption"):
        issues.append(Issue("info", "guests_assumption", g["assumption"]))


# --------------------------------------------------------------------------- filters
def _normalise_value(op: dict, f: dict, issues: list[Issue]) -> dict | None:
    fid = f["id"]
    if f["type"] == "boolean":
        if op.get("bool_value") is None:
            return None
        return {"bool": op["bool_value"]}
    if f["type"] == "range":
        lo, hi = op.get("min"), op.get("max")
        if lo is None and hi is None:
            return None
        if lo is not None and hi is not None and lo > hi:
            lo, hi = hi, lo
            issues.append(Issue("info", "range_swapped", f"Swapped min/max for {f['label']} ({lo}–{hi} {f['unit']}).", [fid]))
        clamped = False
        if lo is not None and not (f["min"] <= lo <= f["max"]):
            lo, clamped = min(max(lo, f["min"]), f["max"]), True
        if hi is not None and not (f["min"] <= hi <= f["max"]):
            hi, clamped = min(max(hi, f["min"]), f["max"]), True
        if clamped:
            issues.append(Issue("warning", "range_clamped",
                                f"{f['label']} limited to the supported range {f['min']}–{f['max']} {f['unit']}.", [fid]))
        return {"min": lo, "max": hi, "unit": f["unit"]}
    values = [v for v in (op.get("enum_values") or []) if v in f.get("options", [])]
    return {"values": values} if values else None


def _is_on(entry: dict) -> bool:
    return entry.get("bool") is True or "min" in entry or "values" in entry


def _apply_filters(s: SearchState, ops: list[dict], catalog: Catalog, features: set[str] | None,
                   issues: list[Issue], applied: list[str], rejected: list[dict],
                   unsupported_currency: bool = False) -> None:
    staged: dict[str, dict] = {}
    contradicted: set[str] = set()
    for op in ops:
        fid = op["filter_id"]
        f = catalog.get(fid)
        if f is None:
            rejected.append({"filter_id": fid, "reason": "unknown_filter"})
            continue
        if op["op"] == "remove":
            if s.filters.pop(fid, None) is not None:
                applied.append(f"-{fid}")
            continue
        if f.get("unit") == "EUR" and unsupported_currency:
            rejected.append({"filter_id": fid, "reason": "currency_conversion_unavailable"})
            continue
        if fid in contradicted:
            rejected.append({"filter_id": fid, "reason": "contradiction"})
            continue
        value = _normalise_value(op, f, issues)
        if value is None:
            rejected.append({"filter_id": fid, "reason": f"invalid_value_for_{f['type']}"})
            continue
        need = f.get("requires_geo_feature")
        if need and features is not None and need not in features and value.get("bool") is not False:
            issues.append(Issue("warning", "geo_impossible",
                                f"'{f['label']}' is not possible in {s.destination['name']} (no {need.replace('_', ' ')}).", [fid]))
            rejected.append({"filter_id": fid, "reason": "geo_impossible"})
            continue
        if fid in staged and staged[fid].get("bool") != value.get("bool"):
            issues.append(Issue("blocking", "contradiction_same_message",
                                f"'{f['label']}' was both requested and excluded.", [fid]))
            staged.pop(fid)
            contradicted.add(fid)
            rejected.append({"filter_id": fid, "reason": "contradiction"})
            continue
        staged[fid] = value | {"importance": op["importance"], "source_quote": op["source_quote"]}

    # 1) contradictions inside this one message -> apply neither, ask the user
    on = [fid for fid, v in staged.items() if _is_on(v)]
    dropped: set[str] = set()
    for i, a in enumerate(on):
        for b in on[i + 1:]:
            if catalog.conflicts(a, b):
                dropped |= {a, b}
                issues.append(Issue("blocking", "contradiction_same_message",
                                    f"'{catalog.get(a)['label']}' conflicts with '{catalog.get(b)['label']}'.", [a, b]))
    # 1b) "X must be true" + "Y (implied by X) must be false" in the same message
    for a in on:
        for implied in catalog.get(a).get("implies", []):
            if staged.get(implied, {}).get("bool") is False:
                dropped |= {a, implied}
                issues.append(Issue("blocking", "contradiction_same_message",
                                    f"'{catalog.get(a)['label']}' requires '{catalog.get(implied)['label']}'.", [a, implied]))
    for fid in sorted(dropped):
        staged.pop(fid, None)
        rejected.append({"filter_id": fid, "reason": "contradiction"})

    # 2) conflicts with the existing state -> latest statement wins
    for fid, v in staged.items():
        if _is_on(v):
            for old in [o for o, ov in s.filters.items() if _is_on(ov) and catalog.conflicts(fid, o)]:
                s.filters.pop(old)
                issues.append(Issue("info", "replaced_previous",
                                    f"Replaced '{catalog.get(old)['label']}' with '{catalog.get(fid)['label']}'.", [old, fid]))
        s.filters[fid] = v
        applied.append(f"+{fid}")

    # 3) redundancy (king bed already implies double bed) and soft tensions
    for fid in list(s.filters):
        for implied in catalog.get(fid).get("implies", []):
            if implied in s.filters and s.filters[implied].get("bool") is True and \
                    s.filters[implied]["importance"] == s.filters[fid]["importance"]:
                s.filters.pop(implied)
    active = [fid for fid, v in s.filters.items() if _is_on(v)]
    for i, a in enumerate(active):
        for b in active[i + 1:]:
            if catalog.soft_conflicts(a, b):
                issues.append(Issue("warning", "soft_conflict",
                                    f"'{catalog.get(a)['label']}' and '{catalog.get(b)['label']}' rarely go together.", [a, b]))


def _plausibility(s: SearchState, issues: list[Issue]) -> None:
    stars = s.filters.get("rating.stars", {})
    price = s.filters.get("price.per_night", {})
    if (stars.get("min") or 0) >= 5 and price.get("max") is not None and price["max"] < 120:
        issues.append(Issue("warning", "implausible_combo",
                            "5-star hotels under €120/night are very rare.", ["rating.stars", "price.per_night"]))


def next_occurrence(month: int, day: int, today: date) -> date:
    """Helper used by tests/examples: the next not-past occurrence of a day-month."""
    d = date(today.year, month, day)
    return d if d >= today else date(today.year + 1, month, day)


__all__ = ["SearchState", "Issue", "PatchResult", "apply_patch", "next_occurrence"]
