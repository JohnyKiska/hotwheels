import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import Base
from app.models import (
    Casting,
    CastingOrigin,
    Evidence,
    EvidenceCastingOrigin,
    EvidenceOriginObject,
    EvidenceOriginSpecification,
    EvidenceOriginVariant,
    OriginObject,
    OriginSpecification,
    OriginVariant,
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


def test_origin_object_can_have_optional_variant_and_scoped_specifications(session):
    skyline = OriginObject(
        object_type="car",
        make_name="Nissan",
        model_name="Skyline",
        generation="R34",
        production_start_year=1998,
        production_end_year=2002,
        status="confirmed",
    )
    v_spec = OriginVariant(
        origin_object=skyline,
        name="GT-R V-Spec II",
        production_start_year=2000,
        production_end_year=2002,
        status="confirmed",
    )
    object_spec = OriginSpecification(
        origin_object=skyline, key="body_style", value="coupe"
    )
    variant_spec = OriginSpecification(
        origin_variant=v_spec, key="drivetrain", value="AWD"
    )
    session.add_all([skyline, v_spec, object_spec, variant_spec])
    session.commit()

    session.expire_all()
    loaded = session.scalar(
        select(OriginObject).where(OriginObject.model_name == "Skyline")
    )
    assert loaded.generation == "R34"
    assert loaded.variants[0].name == "GT-R V-Spec II"
    assert loaded.specifications[0].key == "body_style"
    assert loaded.variants[0].specifications[0].value == "AWD"


def test_origin_specification_must_belong_to_exactly_one_scope(session):
    skyline = OriginObject(make_name="Nissan", model_name="Skyline")
    session.add(skyline)
    session.flush()

    invalid_none = OriginSpecification(key="power", value="206 kW")
    invalid_both = OriginSpecification(
        origin_object=skyline,
        key="power",
        value="206 kW",
    )
    session.add(invalid_none)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()

    session.add(skyline)
    session.flush()
    variant = OriginVariant(origin_object=skyline, name="GT-R")
    session.add(variant)
    session.flush()
    invalid_both = OriginSpecification(
        origin_object_id=skyline.id,
        origin_variant_id=variant.id,
        key="power",
        value="206 kW",
    )
    session.add(invalid_both)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_casting_can_have_multiple_candidates_without_claiming_confirmation(session):
    casting = Casting(name="Nissan Skyline")
    skyline_r34 = OriginObject(
        make_name="Nissan", model_name="Skyline", generation="R34"
    )
    skyline_r33 = OriginObject(
        make_name="Nissan", model_name="Skyline", generation="R33"
    )
    session.add_all([casting, skyline_r34, skyline_r33])
    session.flush()

    candidate_a = CastingOrigin(
        casting=casting,
        origin_object=skyline_r34,
        role="possible_match",
        status="candidate",
        confidence=0.65,
        note="Visual candidate only; not yet verified.",
    )
    candidate_b = CastingOrigin(
        casting=casting,
        origin_object=skyline_r33,
        role="inspired_by",
        status="under_review",
    )
    session.add_all([candidate_a, candidate_b])
    session.commit()

    assert session.query(CastingOrigin).filter_by(casting_id=casting.id).count() == 2
    assert {link.status for link in casting.origin_links} == {"candidate", "under_review"}


def test_casting_origin_variant_must_belong_to_the_linked_origin_object(session):
    casting = Casting(name="Skyline casting")
    skyline = OriginObject(make_name="Nissan", model_name="Skyline", generation="R34")
    supra = OriginObject(make_name="Toyota", model_name="Supra", generation="A80")
    variant = OriginVariant(origin_object=supra, name="RZ")
    session.add_all([casting, skyline, supra, variant])
    session.flush()

    invalid_link = CastingOrigin(
        casting_id=casting.id,
        origin_object_id=skyline.id,
        origin_variant_id=variant.id,
        role="depicts",
    )
    session.add(invalid_link)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_origin_year_ranges_and_candidate_confidence_are_constrained(session):
    session.add(
        OriginObject(
            make_name="Nissan",
            model_name="Skyline",
            production_start_year=2002,
            production_end_year=1998,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()

    casting = Casting(name="Skyline")
    origin = OriginObject(make_name="Nissan", model_name="Skyline")
    session.add_all([casting, origin])
    session.flush()
    session.add(
        CastingOrigin(
            casting=casting,
            origin_object=origin,
            confidence=1.5,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_existing_source_and_evidence_can_support_origin_claims(session):
    source = Source(
        name="Manufacturer archive",
        source_type="website",
        access_status="available",
    )
    session.add(source)
    session.flush()
    record = SourceRecord(
        source=source,
        record_type="vehicle_specification",
        record_url="https://example.invalid/skyline",
    )
    session.add(record)
    session.flush()

    evidence = Evidence(
        source_record=record,
        attribute_name="engine_code",
        observed_value="RB26DETT",
        assessment="supports",
        review_status="pending",
    )
    skyline = OriginObject(make_name="Nissan", model_name="Skyline", generation="R34")
    variant = OriginVariant(origin_object=skyline, name="GT-R")
    specification = OriginSpecification(
        origin_variant=variant,
        key="engine_code",
        value="RB26DETT",
    )
    casting = Casting(name="Nissan Skyline")
    casting_origin = CastingOrigin(
        casting=casting,
        origin_object=skyline,
        origin_variant=variant,
        role="depicts",
        status="under_review",
    )
    session.add_all([evidence, skyline, specification, casting, casting_origin])
    session.flush()
    session.add_all([
        EvidenceOriginObject(evidence=evidence, origin_object=skyline, role="about"),
        EvidenceOriginVariant(evidence=evidence, origin_variant=variant, role="about"),
        EvidenceOriginSpecification(
            evidence=evidence, origin_specification=specification, role="supports"
        ),
        EvidenceCastingOrigin(
            evidence=evidence, casting_origin=casting_origin, role="supports"
        ),
    ])
    session.commit()

    session.expire_all()
    loaded = session.scalar(select(Evidence).where(Evidence.attribute_name == "engine_code"))
    assert loaded.source_record.source.name == "Manufacturer archive"
    assert loaded.origin_object_links[0].origin_object.generation == "R34"
    assert loaded.origin_variant_links[0].origin_variant.name == "GT-R"
    assert loaded.origin_specification_links[0].origin_specification.value == "RB26DETT"
    assert loaded.casting_origin_links[0].casting_origin.status == "under_review"


def test_unknown_or_non_vehicle_origins_are_supported_without_fake_real_car_data(session):
    fictional = OriginObject(
        object_type="fictional",
        make_name=None,
        model_name="Fictional concept",
        status="candidate",
    )
    session.add(fictional)
    session.commit()

    assert fictional.make_name is None
    assert fictional.object_type == "fictional"
