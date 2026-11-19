import base64
import copy
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app import ebay_notifications_api as ebay_api


BACKEND_DIR = Path(__file__).resolve().parents[1]
OFFICIAL_VECTOR_PATH = BACKEND_DIR / "test_ebay_official_vector.json"


@pytest.fixture(autouse=True)
def block_ebay_network(monkeypatch):
    def forbid_network(*_args, **_kwargs):
        raise AssertionError("eBay network access is not allowed in tests")

    monkeypatch.setattr(ebay_api.requests, "get", forbid_network)
    monkeypatch.setattr(ebay_api.requests, "post", forbid_network)


@pytest.fixture
def api_client(monkeypatch):
    for name in (
        "HW_EBAY_DELETION_VERIFICATION_TOKEN",
        "HW_EBAY_DELETION_ENDPOINT_URL",
    ):
        monkeypatch.delenv(name, raising=False)

    application = FastAPI()
    application.include_router(ebay_api.router)
    application.dependency_overrides[ebay_api.get_db] = lambda: pytest.fail(
        "The account-deletion API tests must not access a database"
    )
    return TestClient(application)


def _official_vector():
    contents = OFFICIAL_VECTOR_PATH.read_text(encoding="utf-8")
    return json.loads(contents)["VALID"]


def _signature_header(signature, key_id, digest):
    header = {
        "alg": "ECDSA",
        "kid": key_id,
        "signature": base64.b64encode(signature).decode("ascii"),
        "digest": digest,
    }
    return base64.b64encode(
        json.dumps(header, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")


def _canonical_payload(payload):
    return json.dumps(
        payload,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _signed_payload():
    private_key = ec.generate_private_key(ec.SECP256R1())
    payload = {
        "metadata": {"topic": "MARKETPLACE_ACCOUNT_DELETION"},
        "notification": {"notificationId": "test-notification"},
    }
    signature = private_key.sign(
        _canonical_payload(payload),
        ec.ECDSA(hashes.SHA256()),
    )
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    public_key_data = {
        "key": base64.b64encode(public_key).decode("ascii"),
        "digest": "SHA256",
    }
    return payload, signature, public_key_data


def test_get_challenge_returns_sha256_response(api_client, monkeypatch):
    challenge = "test-challenge"
    token = "a" * 32
    endpoint_url = (
        "https://catalog.example.invalid/"
        "api/v1/integrations/ebay/account-deletion"
    )
    monkeypatch.setenv("HW_EBAY_DELETION_VERIFICATION_TOKEN", token)
    monkeypatch.setenv("HW_EBAY_DELETION_ENDPOINT_URL", endpoint_url)

    response = api_client.get(
        "/api/v1/integrations/ebay/account-deletion",
        params={"challenge_code": challenge},
    )

    expected = hashlib.sha256(
        (challenge + token + endpoint_url).encode("utf-8")
    ).hexdigest()
    assert response.status_code == 200
    assert response.json() == {"challengeResponse": expected}


@pytest.mark.parametrize(
    ("present_variable", "present_value"),
    [
        ("HW_EBAY_DELETION_ENDPOINT_URL", "https://catalog.example.invalid/"),
        ("HW_EBAY_DELETION_VERIFICATION_TOKEN", "a" * 32),
    ],
)
def test_get_challenge_requires_both_settings(
    api_client, monkeypatch, present_variable, present_value
):
    monkeypatch.setenv(present_variable, present_value)

    response = api_client.get(
        "/api/v1/integrations/ebay/account-deletion",
        params={"challenge_code": "test-challenge"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "eBay notification configuration is missing."
    )


@pytest.mark.parametrize(
    "url",
    [
        "/api/v1/integrations/ebay/account-deletion",
        "/api/v1/integrations/ebay/account-deletion?challenge_code=",
    ],
)
def test_get_challenge_rejects_missing_or_empty_challenge(api_client, url):
    response = api_client.get(url)

    assert response.status_code == 422


def test_signature_accepts_official_ebay_vector():
    sample = _official_vector()

    with patch.object(
        ebay_api,
        "_get_public_key",
        return_value=sample["response"],
    ) as get_public_key:
        assert ebay_api._verify_ebay_signature(
            sample["signature"],
            sample["message"],
        )

    get_public_key.assert_called_once_with(sample["public_key"])


def test_signature_rejects_modified_official_vector_payload():
    sample = _official_vector()
    modified_payload = copy.deepcopy(sample["message"])
    modified_payload["notification"]["notificationId"] = "modified"

    with patch.object(
        ebay_api,
        "_get_public_key",
        return_value=sample["response"],
    ):
        assert not ebay_api._verify_ebay_signature(
            sample["signature"],
            modified_payload,
        )


def test_signature_accepts_locally_generated_signature():
    payload, signature, public_key = _signed_payload()

    with patch.object(
        ebay_api,
        "_get_public_key",
        return_value=public_key,
    ) as get_public_key:
        assert ebay_api._verify_ebay_signature(
            _signature_header(signature, "local-test-key", "SHA256"),
            payload,
        )

    get_public_key.assert_called_once_with("local-test-key")


def test_signature_rejects_invalid_signature():
    payload, _signature, public_key = _signed_payload()

    with patch.object(
        ebay_api,
        "_get_public_key",
        return_value=public_key,
    ):
        assert not ebay_api._verify_ebay_signature(
            _signature_header(
                b"not a valid ECDSA signature",
                "local-test-key",
                "SHA256",
            ),
            payload,
        )
