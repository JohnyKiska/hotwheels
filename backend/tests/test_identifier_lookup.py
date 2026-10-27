from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.identifier_lookup import find_identifier_matches
from app.models import (
    CatalogIdentifier,
    Casting,
    IdentifierType,
    Release,
    ReleaseIdentifier,
)


def make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_lookup_returns_empty_result_when_identifier_is_unknown():
    with make_session() as session:
        result = find_identifier_matches(session, "sku", "JHW40-K5N7")
        assert result == {"identifier": None, "matches": [], "ambiguous": False}


def test_lookup_returns_linked_releases_and_marks_multiple_releases_ambiguous():
    with make_session() as session:
        kind = IdentifierType(code="sku", label="SKU")
        casting = Casting(name="Example casting", status="confirmed")
        session.add_all([kind, casting])
        session.flush()

        identifier = CatalogIdentifier(
            identifier_type_id=kind.id,
            value="JHW40-K5N7",
            normalized_value="JHW40-K5N7",
        )
        session.add(identifier)
        session.flush()

        release_a = Release(
            casting_id=casting.id,
            catalog_year=2025,
            name="Example casting",
            status="confirmed",
        )
        release_b = Release(
            casting_id=casting.id,
            catalog_year=2026,
            name="Example casting",
            status="candidate",
        )
        session.add_all([release_a, release_b])
        session.flush()
        session.add_all([
            ReleaseIdentifier(
                release_id=release_a.id,
                identifier_id=identifier.id,
                role="primary",
                source_note="package label",
            ),
            ReleaseIdentifier(
                release_id=release_b.id,
                identifier_id=identifier.id,
                role="primary",
                source_note="conflicting source",
            ),
        ])
        session.commit()

        result = find_identifier_matches(session, "SKU", " jhw40-k5n7 ")

        assert result["identifier"]["value"] == "JHW40-K5N7"
        assert result["ambiguous"] is True
        assert {item["catalog_year"] for item in result["matches"]} == {2025, 2026}
        assert {item["entity_type"] for item in result["matches"]} == {"release"}
