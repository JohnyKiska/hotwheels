from copy import deepcopy

import pytest

from app.importers.casting_grouping import build_casting_grouping_preview


def row(record_id, *, year=2024, product_line="Mainline", number="001",
        sku=None, name="Example model", casting_id=None, claims=None):
    return {
        "record_id": record_id,
        "release_id": f"release-{record_id}",
        "product_line": product_line,
        "catalog_year": year,
        "collector_number_claims": claims if claims is not None else [number] if number is not None else [],
        "sku": [sku] if sku else [],
        "model_name": name,
        "existing_casting_id": casting_id,
        "source_record_ids": [f"source-{record_id}"],
    }


def test_same_context_and_collector_number_groups_distinct_skus():
    result = build_casting_grouping_preview([
        row("one", sku="ABC12", number="001"),
        row("two", sku="DEF34", number="001", name="Example model (2nd Color)"),
    ])

    assert result["writes_to_catalog"] is False
    assert len(result["groups"]) == 1
    assert {record["sku"][0] for record in result["groups"][0]["records"]} == {"ABC12", "DEF34"}
    assert result["groups"][0]["status"] == "proposed"


def test_same_name_with_different_collector_numbers_stays_separate_nissan_skyline_case():
    result = build_casting_grouping_preview([
        row("then-and-now", sku="HTC65", number="191",
            name="Nissan Skyline 2000GT-R LBWK"),
        row("tooned", sku="HRY85", number="213",
            name="Nissan Skyline 2000GT-R LBWK"),
    ])

    assert len(result["groups"]) == 2
    assert {
        (group["group_key"]["collector_number"], group["records"][0]["sku"][0])
        for group in result["groups"]
    } == {("191", "HTC65"), ("213", "HRY85")}


@pytest.mark.parametrize("changes", [
    {"year": 2025},
    {"product_line": "Car Culture"},
])
def test_same_number_in_different_contexts_does_not_group(changes):
    first = row("first", number="007")
    second = row("second", number="007", **changes)
    result = build_casting_grouping_preview([first, second])
    assert len(result["groups"]) == 2


def test_missing_collector_number_requires_review_without_name_fallback():
    result = build_casting_grouping_preview([
        row("missing", number=None, name="Repeated model name"),
    ])

    assert result["groups"] == []
    assert result["manual_review"][0]["reason_codes"] == ["missing_collector_number"]


def test_conflicting_collector_number_claims_require_review():
    result = build_casting_grouping_preview([
        row("conflict", claims=[
            {"value": "191", "source_record_id": "source-a"},
            {"value": "213", "source_record_id": "source-b"},
        ]),
    ])

    assert result["groups"] == []
    assert "conflicting_collector_number_claims" in result["manual_review"][0]["reason_codes"]


def test_conflicting_collector_number_claims_across_snapshots_of_one_release_require_review():
    first = row("snapshot-a", number="191")
    second = row("snapshot-b", number="213")
    first["release_id"] = "same-release"
    second["release_id"] = "same-release"

    result = build_casting_grouping_preview([first, second])

    assert result["groups"] == []
    assert len(result["manual_review"]) == 2
    assert all(
        "conflicting_collector_number_claims_for_release" in item["reason_codes"]
        for item in result["manual_review"]
    )
    assert {
        claim["value"]
        for item in result["manual_review"]
        for claim in item["collector_number_claims"]
    } == {"191", "213"}


def test_one_existing_casting_across_different_proposed_keys_is_flagged_not_merged():
    result = build_casting_grouping_preview([
        row("a", number="191", casting_id="legacy-casting"),
        row("b", number="213", casting_id="legacy-casting"),
    ])

    assert len(result["groups"]) == 2
    assert all(group["requires_manual_review"] for group in result["groups"])
    assert result["conflicts"][0]["code"] == "existing_casting_spans_multiple_proposed_groups"


def test_same_proposed_key_with_multiple_existing_castings_is_not_auto_merged():
    result = build_casting_grouping_preview([
        row("a", number="191", casting_id="casting-a"),
        row("b", number="191", casting_id="casting-b"),
    ])

    assert len(result["groups"]) == 1
    assert result["groups"][0]["status"] == "manual_review"
    assert result["groups"][0]["conflicts"][0]["code"] == "group_spans_multiple_existing_castings"


def test_preview_does_not_mutate_input():
    records = [row("a", number="001")]
    original = deepcopy(records)
    build_casting_grouping_preview(records)
    assert records == original


def test_duplicate_record_ids_are_rejected():
    with pytest.raises(ValueError, match="duplicate record_id"):
        build_casting_grouping_preview([row("same"), row("same")])
