import pytest

from app.identifier_normalization import InvalidIdentifier, normalize_identifier


@pytest.mark.parametrize(
    ("kind", "raw", "expected"),
    [
        ("upc", "0 12345-67890 5", "012345678905"),
        ("ean", " 400638133393-1 ", "4006381333931"),
        ("sku", "jhw 40", "JHW 40"),
        ("sku", " jhw40-k5n7 ", "JHW40-K5N7"),
        ("mattel_product_number", " jmv83-abc ", "JMV83-ABC"),
        ("catalog_number", "  2026 hw-149  ", "2026 HW-149"),
    ],
)
def test_normalize_identifier(kind, raw, expected):
    assert normalize_identifier(kind, raw) == expected


@pytest.mark.parametrize(
    ("kind", "raw"),
    [("upc", "12A34"), ("ean", "123/456"), ("sku", "  "), ("", "123")],
)
def test_invalid_identifier_rejected(kind, raw):
    with pytest.raises(InvalidIdentifier):
        normalize_identifier(kind, raw)


def test_leading_zeroes_are_preserved():
    assert normalize_identifier("upc", "001234567890") == "001234567890"


def test_sku_hyphen_is_preserved_and_not_treated_as_optional():
    assert normalize_identifier("sku", "JHW40-K5N7") != normalize_identifier(
        "sku", "JHW40K5N7"
    )
    assert normalize_identifier("sku", "JHW40-K5N7") != normalize_identifier(
        "sku", "JHW40"
    )
