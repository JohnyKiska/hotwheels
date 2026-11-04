import pytest

from app.importers.preview_diff import build_release_claim_diff


def observation(claims):
    return {
        "mode": "preview_only",
        "writes_to_catalog": False,
        "claims": claims,
    }


def release_snapshot(**overrides):
    result = {
        "id": "release-1",
        "name": "Example Model",
        "casting_name": "Example Model",
        "catalog_year": 2025,
        "assortment_number": None,
        "series_names": ["Factory Fresh"],
    }
    result.update(overrides)
    return result


def test_matching_canonical_value_is_no_change():
    result = build_release_claim_diff(
        observation([{
            "attribute": "model_name",
            "value": " example   model ",
            "raw_value": " example   model ",
            "source_field": "Name",
        }]),
        release_snapshot(),
    )

    claim = result["claims"][0]
    assert claim["status"] == "same"
    assert claim["suggested_action"] == "no_change"
    assert result["writes_to_catalog"] is False


def test_empty_canonical_value_proposes_evidence_only_after_confirmation():
    result = build_release_claim_diff(
        observation([{
            "attribute": "assortment_number",
            "value": "JHW40",
            "raw_value": "JHW40",
            "source_field": "Assortment",
        }]),
        release_snapshot(),
    )

    claim = result["claims"][0]
    assert claim["status"] == "new_evidence"
    assert claim["suggested_action"] == "attach_evidence_after_confirmation"


def test_different_canonical_value_is_a_review_conflict_not_an_overwrite():
    result = build_release_claim_diff(
        observation([{
            "attribute": "catalog_year",
            "value": 2026,
            "raw_value": "2026",
            "source_field": "Catalog year",
        }]),
        release_snapshot(),
    )

    claim = result["claims"][0]
    assert claim["status"] == "conflicting_value"
    assert claim["existing_value"] == 2025
    assert claim["suggested_action"] == "review_conflict"


def test_unmapped_source_attribute_is_preserved_as_evidence_only():
    result = build_release_claim_diff(
        observation([{
            "attribute": "wheels",
            "value": "5-Spoke",
            "raw_value": "5-Spoke",
            "source_field": "Wheels",
        }]),
        release_snapshot(),
    )

    claim = result["claims"][0]
    assert claim["status"] == "evidence_only"
    assert claim["incoming_value"] == "5-Spoke"
    assert claim["suggested_action"] == "attach_evidence_after_confirmation"


def test_missing_claim_value_is_insufficient_evidence():
    result = build_release_claim_diff(
        observation([{
            "attribute": "model_name",
            "value": None,
            "raw_value": None,
            "source_field": "Name",
        }]),
        release_snapshot(),
    )

    assert result["claims"][0]["status"] == "insufficient_evidence"
    assert result["claims"][0]["suggested_action"] == "manual_review"


def test_series_name_compares_against_selected_release_series():
    result = build_release_claim_diff(
        observation([{
            "attribute": "series_name",
            "value": "Factory Fresh",
            "raw_value": "Factory Fresh",
            "source_field": "Series",
        }]),
        release_snapshot(),
    )

    assert result["claims"][0]["status"] == "same"


def test_diff_requires_explicit_selected_release():
    with pytest.raises(ValueError, match="Release ID"):
        build_release_claim_diff(observation([]), {"name": "Example"})
