import json
from datetime import date
from pathlib import Path

import pytest

from winwin_assistant.catalog import load_catalog
from winwin_assistant.inventory import MockInventory, geo_features
from winwin_assistant.state import SearchState, apply_patch, next_occurrence
from winwin_assistant.tools import ToolRouter

TODAY = date(2026, 9, 27)
ROOT = Path(__file__).resolve().parents[1]
CAT = load_catalog()

KEEP_DEST = {"action": "keep", "name": None, "type": None, "country_code": None, "ambiguous_with": []}
KEEP_DATES = {"action": "keep", "check_in": None, "check_out": None, "flexibility": "exact",
              "window_start": None, "window_end": None, "nights": None, "assumption": None}
KEEP_GUESTS = {"action": "keep", "adults": None, "children_ages": None, "rooms": None, "assumption": None}


def op(fid, b=True, lo=None, hi=None, kind="add", importance="must"):
    rng = lo is not None or hi is not None
    return {"op": kind, "filter_id": fid, "bool_value": None if rng or kind == "remove" else b, "min": lo, "max": hi,
            "enum_values": None, "importance": importance, "source_quote": "test"}


def patch(ops=(), destination=KEEP_DEST, dates=KEEP_DATES, guests=KEEP_GUESTS, reset=False):
    return {"intent": "modify_search", "reset": reset, "destination": destination, "dates": dates, "guests": guests,
            "filter_operations": list(ops), "unmapped_preferences": [], "sort": "keep", "currency": None,
            "user_language": "en"}


def dates(ci, co):
    return KEEP_DATES | {"action": "set", "check_in": ci, "check_out": co}


def guests(adults, kids=(), rooms=1):
    return KEEP_GUESTS | {"action": "set", "adults": adults, "children_ages": list(kids), "rooms": rooms}


def haarlem():
    return KEEP_DEST | {"action": "set", "name": "Haarlem", "type": "city", "country_code": "NL"}


def full_state(*ops):
    return apply_patch(SearchState(), patch(ops, haarlem(), dates("2027-08-15", "2027-08-18"), guests(1)),
                       CAT, TODAY, geo_features).state


# ---------------------------------------------------------------- catalog
def test_catalog_has_1000_plus_filters_with_both_types():
    assert len(CAT.filters) >= 1000
    types = {f["type"] for f in CAT.filters}
    assert {"boolean", "range"} <= types
    assert len(CAT.by_id) == len(CAT.filters), "ids must be unique"


def test_catalog_conflict_references_are_symmetric():
    for f in CAT.filters:
        for other in f.get("conflicts_with", []):
            assert f["id"] in CAT.by_id[other]["conflicts_with"]


# ---------------------------------------------------------------- core slots
def test_year_rollover_for_past_month():
    assert next_occurrence(8, 15, TODAY) == date(2027, 8, 15)
    assert next_occurrence(12, 1, TODAY) == date(2026, 12, 1)


@pytest.mark.parametrize("ci,co,code", [
    ("2027-08-18", "2027-08-15", "dates_order"),
    ("2026-08-15", "2026-08-18", "dates_past"),
    ("2027-01-01", "2027-03-01", "stay_too_long"),
    ("2027-08-15", None, "dates_incomplete"),
])
def test_invalid_dates_are_blocking_and_not_applied(ci, co, code):
    res = apply_patch(SearchState(), patch(dates=dates(ci, co)), CAT, TODAY)
    assert [i.code for i in res.issues if i.severity == "blocking"] == [code]
    assert res.state.dates is None and "dates" in res.missing_required


def test_solo_traveller_and_missing_child_age():
    res = apply_patch(SearchState(), patch(guests=guests(1)), CAT, TODAY)
    assert res.state.guests == {"adults": 1, "children_ages": [], "rooms": 1}
    res = apply_patch(SearchState(), patch(guests=guests(2, [-1])), CAT, TODAY)
    assert "children_ages" in res.missing_required


def test_rooms_need_an_adult_each():
    res = apply_patch(SearchState(), patch(guests=guests(1, [5, 7], rooms=2)), CAT, TODAY)
    assert res.blocking and res.state.guests is None


def test_ambiguous_destination_blocks():
    d = haarlem() | {"name": "Valencia", "ambiguous_with": ["Valencia, Venezuela"]}
    res = apply_patch(SearchState(), patch(destination=d), CAT, TODAY)
    assert res.blocking and res.state.destination is None
    assert "destination" in res.missing_required


@pytest.mark.parametrize("date_patch,code", [
    (dates("2027-02-30", "2027-03-02"), "dates_invalid"),
    (KEEP_DATES | {"action": "set", "window_start": "2027-05-31", "window_end": "2027-05-01",
                   "flexibility": "month"}, "dates_order"),
    (KEEP_DATES | {"action": "set", "window_start": "2027-05-01", "window_end": None,
                   "flexibility": "month"}, "dates_incomplete"),
    (KEEP_DATES | {"action": "set", "window_start": "2027-05-01", "window_end": "2027-05-31",
                   "nights": 0, "flexibility": "month"}, "dates_invalid"),
])
def test_bad_date_windows_are_blocked_without_crashing(date_patch, code):
    res = apply_patch(SearchState(), patch(dates=date_patch), CAT, TODAY)
    assert res.state.dates is None
    assert code in [i.code for i in res.issues]


@pytest.mark.parametrize("guest_patch,code", [
    (guests(2, rooms=0), "rooms_invalid"),
    (guests(2, rooms=-1), "rooms_invalid"),
    (guests(2, kids=[-2]), "children_ages_invalid"),
])
def test_invalid_guest_values_do_not_get_silently_repaired(guest_patch, code):
    res = apply_patch(SearchState(), patch(guests=guest_patch), CAT, TODAY)
    assert res.state.guests is None
    assert code in [i.code for i in res.issues]


# ---------------------------------------------------------------- filters
def test_boolean_and_range_filters_apply():
    s = full_state(op("parking.free_parking"), op("price.per_night", lo=200, hi=400))
    assert s.filters["parking.free_parking"]["bool"] is True
    assert (s.filters["price.per_night"]["min"], s.filters["price.per_night"]["max"]) == (200, 400)


def test_unknown_filter_rejected_not_invented():
    res = apply_patch(SearchState(), patch([op("room.unicorn_pillow")]), CAT, TODAY)
    assert res.rejected == [{"filter_id": "room.unicorn_pillow", "reason": "unknown_filter"}]


def test_range_min_greater_than_max_is_swapped():
    res = apply_patch(SearchState(), patch([op("price.per_night", lo=400, hi=200)]), CAT, TODAY)
    assert res.state.filters["price.per_night"]["min"] == 200
    assert "range_swapped" in [i.code for i in res.issues]


def test_out_of_bounds_range_is_clamped():
    res = apply_patch(SearchState(), patch([op("rating.guest_score", lo=12)]), CAT, TODAY)
    assert res.state.filters["rating.guest_score"]["min"] == 10


def test_non_eur_budget_is_not_silently_interpreted_as_eur():
    p = patch([op("price.per_night", hi=200)]) | {"currency": "USD"}
    res = apply_patch(SearchState(), p, CAT, TODAY)
    assert "price.per_night" not in res.state.filters
    assert res.state.currency == "EUR"
    assert res.rejected[0]["reason"] == "currency_conversion_unavailable"


def test_same_message_contradiction_applies_neither():
    res = apply_patch(SearchState(), patch([op("pets.pets_allowed"), op("pets.no_pets_on_property"),
                                            op("parking.free_parking")]), CAT, TODAY)
    assert "pets.pets_allowed" not in res.state.filters
    assert "pets.no_pets_on_property" not in res.state.filters
    assert "parking.free_parking" in res.state.filters, "the rest of the message is still applied"
    assert res.blocking


def test_repeated_contradiction_cannot_reintroduce_the_filter():
    res = apply_patch(SearchState(), patch([op("pets.pets_allowed", True),
                                            op("pets.pets_allowed", False),
                                            op("pets.pets_allowed", True)]), CAT, TODAY)
    assert "pets.pets_allowed" not in res.state.filters
    assert res.blocking


def test_implied_filter_negated_is_contradiction():
    res = apply_patch(SearchState(), patch([op("beds.king_bed"), op("beds.double_bed", b=False)]), CAT, TODAY)
    assert res.blocking and not res.state.filters


def test_change_of_mind_across_turns_latest_wins():
    s = full_state(op("pets.pets_allowed"))
    res = apply_patch(s, patch([op("pets.no_pets_on_property")]), CAT, TODAY)
    assert "pets.pets_allowed" not in res.state.filters
    assert res.state.filters["pets.no_pets_on_property"]["bool"] is True
    assert "replaced_previous" in [i.code for i in res.issues] and not res.blocking


def test_remove_filter():
    s = full_state(op("bathroom.rain_shower"))
    res = apply_patch(s, patch([op("bathroom.rain_shower", kind="remove")]), CAT, TODAY)
    assert "bathroom.rain_shower" not in res.state.filters and res.applied == ["-bathroom.rain_shower"]


def test_geo_impossible_filter_rejected_for_destination():
    s = full_state()
    res = apply_patch(s, patch([op("location.ski_in_ski_out")]), CAT, TODAY, geo_features)
    assert res.rejected[0]["reason"] == "geo_impossible"


def test_redundant_implied_filter_collapsed():
    s = full_state(op("beds.double_bed"), op("beds.king_bed"))
    assert "beds.king_bed" in s.filters and "beds.double_bed" not in s.filters


def test_soft_conflict_is_only_a_warning():
    res = apply_patch(SearchState(), patch([op("style.quiet_atmosphere"), op("location.near_nightlife")]), CAT, TODAY)
    assert [i.severity for i in res.issues] == ["warning"] and len(res.state.filters) == 2


# ---------------------------------------------------------------- counts & relaxations
def test_count_only_when_core_slots_complete():
    router = ToolRouter(CAT, MockInventory(CAT), TODAY)
    _, result = router.update_search(SearchState(), patch(destination=haarlem()))
    assert result["offer_count"] is None and set(result["missing_required"]) == {"dates", "guests"}


def test_filter_contradiction_does_not_hide_count_but_bad_dates_do():
    router = ToolRouter(CAT, MockInventory(CAT), TODAY)
    s = full_state()
    _, result = router.update_search(s, patch([op("pets.pets_allowed"), op("pets.no_pets_on_property")]))
    assert result["offer_count"] is not None
    _, result = router.update_search(s, patch(dates=dates("2027-08-18", "2027-08-15")))
    assert result["offer_count"] is None


def test_zero_results_come_with_relaxations_that_help():
    inv = MockInventory(CAT)
    s = full_state(*[op(f["id"]) for f in CAT.filters[200:240] if f["type"] == "boolean"])
    assert inv.count(s) == 0
    relax = inv.relaxations(s)
    assert relax and all(r["new_count"] > 0 for r in relax)


def test_relaxations_never_drop_protected_needs_or_invent_shift_counts():
    inv = MockInventory(CAT)
    s = full_state(op("pets.no_pets_on_property"), op("accessibility.wheelchair_accessible"),
                   op("style.quiet_atmosphere"))
    for option in inv.relaxations(s):
        assert not {"pets.no_pets_on_property", "accessibility.wheelchair_accessible"} & set(option["remove"])
        if option["change"].startswith("shift dates"):
            shifted = SearchState.from_dict(s.to_dict())
            from datetime import timedelta
            delta = timedelta(days=-1 if "14 Aug" in option["change"] else 1)
            shifted.dates = s.dates | {
                "check_in": (date.fromisoformat(s.dates["check_in"]) + delta).isoformat(),
                "check_out": (date.fromisoformat(s.dates["check_out"]) + delta).isoformat()}
            assert option["new_count"] == inv.count(shifted)


def test_examples_are_in_sync_with_backend():
    """Guards the write-up: the numbers quoted in examples come from the code."""
    turns = json.loads((ROOT / "examples" / "conversation.json").read_text())["turns"]
    router = ToolRouter(CAT, MockInventory(CAT), TODAY)
    state = SearchState()
    for turn in turns:
        for call in turn["tool_calls"]:
            state, result = router.update_search(state, call["arguments"])
            assert result == turn["tool_result"], turn["turn"]
            count = result["offer_count"]
            if count is not None:
                assert f"**{count} hotel" in turn["assistant_reply"]["message"], turn["turn"]


def test_config_tool_schemas_are_strict_compatible():
    cfg = json.loads((ROOT / "assistant" / "config.json").read_text())

    def check(node):
        if isinstance(node, dict):
            if node.get("type") == "object" or node.get("type") == ["object", "null"]:
                assert node.get("additionalProperties") is False
                assert set(node["required"]) == set(node["properties"]), node["required"]
            for v in node.values():
                check(v)
        elif isinstance(node, list):
            for v in node:
                check(v)

    for tool in cfg["tools"]:
        check(tool["parameters"])
    check(cfg["response_format"]["schema"])


@pytest.mark.parametrize("phrase,expected", [
    ("reading light on both sides of the bed", "beds.reading_lights_both_sides"),
    ("rain shower", "bathroom.rain_shower"),
    ("coworking-style lounge", "connectivity.coworking_space"),
    ("real double bed", "beds.double_bed"),
    ("staff speaking Dutch", "language.staff_speaks_dutch"),
    ("good soundproofing", "beds.soundproofing"),
    ("not a big chain", "style.independent"),
    ("floor space to stretch or do yoga", "room.floor_space_exercise"),
    ("pet friendly", "pets.pets_allowed"),
    ("strong in-room Wi-Fi", "connectivity.wifi_speed"),
])
def test_catalog_search_finds_haarlem_phrases(phrase, expected):
    assert CAT.search(phrase)[0]["id"] == expected
