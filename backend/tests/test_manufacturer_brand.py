import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import Base
from app.models import (
    Brand,
    Casting,
    CastingBrand,
    Evidence,
    EvidenceBrand,
    EvidenceManufacturer,
    Manufacturer,
    ManufacturerBrand,
    Release,
    ReleaseBrand,
    Source,
    SourceRecord,
)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db
    engine.dispose()


def test_manufacturer_and_brand_are_separate_entities(session):
    manufacturer = Manufacturer(name="Mattel, Inc.", legal_name="Mattel, Inc.")
    brand = Brand(name="Hot Wheels")
    manufacturer.brand_links.append(
        ManufacturerBrand(brand=brand, relationship_type="owner", valid_from_year=1968)
    )
    session.add(manufacturer)
    session.commit()

    loaded = session.scalar(select(Brand).where(Brand.id == brand.id))
    assert loaded is not None
    assert loaded.name == "Hot Wheels"
    assert loaded.manufacturer_links[0].manufacturer.name == "Mattel, Inc."
    assert loaded.manufacturer_links[0].valid_from_year == 1968
    assert loaded.id != manufacturer.id


def test_one_manufacturer_can_have_multiple_brands(session):
    manufacturer = Manufacturer(name="Example Group")
    brand_a = Brand(name="Brand A")
    brand_b = Brand(name="Brand B")
    manufacturer.brand_links.extend([
        ManufacturerBrand(brand=brand_a, relationship_type="owner"),
        ManufacturerBrand(brand=brand_b, relationship_type="producer"),
    ])
    session.add(manufacturer)
    session.commit()

    assert {link.brand.name for link in manufacturer.brand_links} == {"Brand A", "Brand B"}


def test_casting_and_release_can_have_distinct_brand_links(session):
    casting = Casting(name="Example casting")
    release = Release(casting=casting, catalog_year=2026)
    brand_a = Brand(name="Hot Wheels")
    brand_b = Brand(name="Promotional partner")
    casting.brand_links.append(CastingBrand(brand=brand_a, role="primary"))
    release.brand_links.append(ReleaseBrand(brand=brand_b, role="promotional"))
    session.add(release)
    session.commit()

    assert [link.brand.name for link in casting.brand_links] == ["Hot Wheels"]
    assert [link.brand.name for link in release.brand_links] == ["Promotional partner"]


def test_evidence_can_support_manufacturer_and_brand(session):
    source = Source(name="Catalog", source_type="website")
    record = SourceRecord(source=source, record_type="catalog_entry")
    evidence = Evidence(source_record=record, attribute_name="brand", observed_value="Hot Wheels")
    manufacturer = Manufacturer(name="Mattel")
    brand = Brand(name="Hot Wheels")
    evidence.brand_links.append(EvidenceBrand(brand=brand))
    evidence.manufacturer_links.append(EvidenceManufacturer(manufacturer=manufacturer))
    session.add(evidence)
    session.commit()

    assert evidence.brand_links[0].brand.name == "Hot Wheels"
    assert evidence.manufacturer_links[0].manufacturer.name == "Mattel"


def test_manufacturer_brand_year_range_is_validated(session):
    manufacturer = Manufacturer(name="Example company")
    brand = Brand(name="Example brand")
    session.add(ManufacturerBrand(
        manufacturer=manufacturer,
        brand=brand,
        valid_from_year=2020,
        valid_to_year=2010,
    ))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_referenced_brand_cannot_be_deleted(session):
    brand = Brand(name="Hot Wheels")
    casting = Casting(name="Example casting")
    casting.brand_links.append(CastingBrand(brand=brand))
    session.add(casting)
    session.commit()

    session.delete(brand)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
