
import asyncio
import copy
import hashlib
import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

from app.main import app
import app.ebay_notifications_api as ebay_api
from app.models import EbaySeller, EbayListing, EbayNotification


test_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

TestSession = sessionmaker(
    bind=test_engine,
    autoflush=False,
    autocommit=False,
)

EbaySeller.__table__.create(bind=test_engine)
EbayListing.__table__.create(bind=test_engine)
EbayNotification.__table__.create(bind=test_engine)


def override_get_db():
    db = TestSession()
    try:
        yield db
    finally:
        db.close()

def seed_test_data():
    db = TestSession()

    seller = EbaySeller(
        ebay_user_id="test-user-123",
        username="test-seller",
        display_name="Test Seller",
        profile_url="https://example.com/seller",
    )
    db.add(seller)
    db.flush()

    db.add(
        EbayListing(
            ebay_item_id="test-item-001",
            seller_id=seller.id,
            title="Hot Wheels Test Car",
            item_url="https://example.com/item",
            price_amount=10.99,
            currency="USD",
            condition="New",
        )
    )

    other_seller = EbaySeller(
        ebay_user_id="other-user-456",
        username="other-seller",
        display_name="Other Seller",
        profile_url="https://example.com/other-seller",
    )
    db.add(other_seller)
    db.flush()

    db.add(
        EbayListing(
            ebay_item_id="other-item-002",
            seller_id=other_seller.id,
            title="Hot Wheels Other Car",
            item_url="https://example.com/other-item",
            price_amount=15.99,
            currency="USD",
            condition="New",
        )
    )

    third_seller = EbaySeller(
        ebay_user_id="third-user-789",
        username="third-seller",
        display_name="Third Seller",
        profile_url="https://example.com/third-seller",
    )
    db.add(third_seller)
    db.flush()

    db.add(
        EbayListing(
            ebay_item_id="third-item-003",
            seller_id=third_seller.id,
            title="Hot Wheels Third Car",
            item_url="https://example.com/third-item",
            price_amount=19.99,
            currency="USD",
            condition="New",
        )
    )

    db.commit()
    db.close()

PAYLOAD = {
    "metadata": {
        "topic": "MARKETPLACE_ACCOUNT_DELETION",
    },
    "notification": {
        "notificationId": "test-notification-001",
        "eventDate": "2026-11-19T03:00:00Z",
        "publishDate": "2026-11-19T03:01:00Z",
        "publishAttemptCount": 1,
        "data": {
            "userId": "test-user-123",
            "username": "test-seller",
            "eiasToken": "secret-test-token",
        },
    },
}

class EbayNotificationTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        app.dependency_overrides[ebay_api.get_db] = override_get_db
        seed_test_data()
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.pop(ebay_api.get_db, None)
        test_engine.dispose()

    def test_01_missing_signature(self):
        response = self.client.post(
            "/api/v1/integrations/ebay/account-deletion",
            json=PAYLOAD,
        )

        self.assertEqual(response.status_code, 412)

        db = TestSession()
        self.assertEqual(db.query(EbayNotification).count(), 0)
        db.close()

        print("PASS: Missing signature rejected.")

    def test_02_invalid_signature(self):
        with patch.object(
            ebay_api,
            "_verify_ebay_signature",
            return_value=False,
        ):
            response = self.client.post(
                "/api/v1/integrations/ebay/account-deletion",
                json=PAYLOAD,
                headers={"X-EBAY-SIGNATURE": "fake-signature"},
            )

        self.assertEqual(response.status_code, 412)

        db = TestSession()
        self.assertEqual(db.query(EbayNotification).count(), 0)
        db.close()

        print("PASS: Invalid signature rejected.")

    def test_03_valid_notification(self):
        with patch.object(
            ebay_api,
            "_verify_ebay_signature",
            return_value=True,
        ):
            response = self.client.post(
                "/api/v1/integrations/ebay/account-deletion",
                json=PAYLOAD,
                headers={"X-EBAY-SIGNATURE": "fake-valid-signature"},
            )

        self.assertEqual(response.status_code, 204)

        db = TestSession()

        seller = db.query(EbaySeller).filter_by(
            ebay_user_id=None
        ).one()

        listing = db.query(EbayListing).filter_by(
            ebay_item_id="test-item-001"
        ).one()

        notification = db.query(EbayNotification).filter_by(
            notification_id="test-notification-001"
        ).one()

        self.assertIsNone(seller.username)
        self.assertEqual(seller.status, "anonymized")
        self.assertIsNone(listing.title)
        self.assertEqual(listing.listing_status, "anonymized")
        self.assertEqual(notification.status, "processed")
        self.assertTrue(notification.signature_valid)
        self.assertIsNotNone(notification.payload_sha256)
        self.assertNotIn(
            "secret-test-token",
            str(notification.__dict__),
        )

        # Проверяем, что второй продавец не затронут.
        other_seller = db.query(EbaySeller).filter_by(
            ebay_user_id="other-user-456"
        ).one()

        other_listing = db.query(EbayListing).filter_by(
            ebay_item_id="other-item-002"
        ).one()

        self.assertEqual(other_seller.username, "other-seller")
        self.assertEqual(other_seller.status, "active")
        self.assertEqual(other_listing.title, "Hot Wheels Other Car")
        self.assertEqual(other_listing.listing_status, "active")
        self.assertIsNone(other_listing.anonymized_at)

        db.close()

        print("PASS: Notification processed and seller anonymized.")

    def test_04_duplicate_notification(self):
        with patch.object(
            ebay_api,
            "_verify_ebay_signature",
            return_value=True,
        ):
            first = self.client.post(
                "/api/v1/integrations/ebay/account-deletion",
                json=PAYLOAD,
                headers={"X-EBAY-SIGNATURE": "fake-valid-signature"},
            )

            second = self.client.post(
                "/api/v1/integrations/ebay/account-deletion",
                json=PAYLOAD,
                headers={"X-EBAY-SIGNATURE": "fake-valid-signature"},
            )

        self.assertEqual(first.status_code, 204)
        self.assertEqual(second.status_code, 204)

        db = TestSession()

        self.assertEqual(
            db.query(EbayNotification).filter_by(
                notification_id="test-notification-001"
            ).count(),
            1,
        )

        db.close()

        print("PASS: Duplicate notification ignored.")


    def test_05_unknown_seller(self):
        unknown_payload = {
            "metadata": {
                "topic": "MARKETPLACE_ACCOUNT_DELETION",
            },
            "notification": {
                "notificationId": "test-notification-unknown",
                "eventDate": "2026-11-19T03:00:00Z",
                "publishDate": "2026-11-19T03:01:00Z",
                "publishAttemptCount": 1,
                "data": {
                    "userId": "unknown-user-999",
                    "eiasToken": "secret-unknown-token",
                },
            },
        }

        with patch.object(
            ebay_api,
            "_verify_ebay_signature",
            return_value=True,
        ):
            response = self.client.post(
                "/api/v1/integrations/ebay/account-deletion",
                json=unknown_payload,
                headers={"X-EBAY-SIGNATURE": "fake-valid-signature"},
            )

        self.assertEqual(response.status_code, 204)

        db = TestSession()

        seller = db.query(EbaySeller).filter_by(
            ebay_user_id="other-user-456"
        ).one()

        listing = db.query(EbayListing).filter_by(
            ebay_item_id="other-item-002"
        ).one()

        self.assertEqual(seller.username, "other-seller")
        self.assertEqual(listing.title, "Hot Wheels Other Car")

        notification = db.query(EbayNotification).filter_by(
            notification_id="test-notification-unknown"
        ).one()

        self.assertEqual(notification.status, "processed")

        db.close()

        print("PASS: Unknown seller does not affect existing records.")



    def test_06_unrelated_topic_ignored(self):
        unrelated_payload = {
            "metadata": {
                "topic": "ITEM_PRICE_REVISION",
            },
            "notification": {
                "notificationId": "test-notification-unrelated",
                "eventDate": "2026-11-19T03:00:00Z",
                "publishDate": "2026-11-19T03:01:00Z",
                "publishAttemptCount": 1,
                "data": {
                    "userId": "test-user-123",
                },
            },
        }

        with patch.object(
            ebay_api,
            "_verify_ebay_signature",
            return_value=True,
        ):
            response = self.client.post(
                "/api/v1/integrations/ebay/account-deletion",
                json=unrelated_payload,
                headers={"X-EBAY-SIGNATURE": "fake-valid-signature"},
            )

        self.assertEqual(response.status_code, 204)

        db = TestSession()

        seller = db.query(EbaySeller).filter_by(
            ebay_user_id="other-user-456"
        ).one()

        listing = db.query(EbayListing).filter_by(
            ebay_item_id="other-item-002"
        ).one()

        notification = db.query(EbayNotification).filter_by(
            notification_id="test-notification-unrelated"
        ).one()

        self.assertEqual(seller.username, "other-seller")
        self.assertEqual(seller.status, "active")
        self.assertEqual(listing.title, "Hot Wheels Other Car")
        self.assertEqual(listing.listing_status, "active")
        self.assertEqual(notification.status, "ignored")

        db.close()

        print("PASS: Unrelated topic ignored without data changes.")


    def test_07_failed_processing_saved(self):
        from datetime import datetime, timezone

        failed_payload = {
            "metadata": {
                "topic": "MARKETPLACE_ACCOUNT_DELETION",
            },
            "notification": {
                "notificationId": "test-notification-failed",
                "eventDate": "2026-11-19T03:00:00Z",
                "publishDate": "2026-11-19T03:01:00Z",
                "publishAttemptCount": 1,
                "data": {
                    "userId": "other-user-456",
                },
            },
        }

        with patch.object(
            ebay_api,
            "_verify_ebay_signature",
            return_value=True,
        ), patch.object(
            ebay_api,
            "_utc_now",
            side_effect=[
                datetime.now(timezone.utc),
                RuntimeError("Simulated processing failure"),
            ],
        ):
            response = self.client.post(
                "/api/v1/integrations/ebay/account-deletion",
                json=failed_payload,
                headers={"X-EBAY-SIGNATURE": "fake-valid-signature"},
            )

        self.assertEqual(response.status_code, 503)

        db = TestSession()

        notification = db.query(EbayNotification).filter_by(
            notification_id="test-notification-failed"
        ).one()

        seller = db.query(EbaySeller).filter_by(
            ebay_user_id="other-user-456"
        ).one()

        self.assertEqual(notification.status, "failed")
        self.assertIsNotNone(notification.last_error)
        self.assertEqual(seller.status, "active")

        db.close()

        print("PASS: Failed processing saved and transaction rolled back.")


    def test_08_failed_notification_retry(self):
        retry_payload = {
            "metadata": {
                "topic": "MARKETPLACE_ACCOUNT_DELETION",
            },
            "notification": {
                "notificationId": "test-notification-failed",
                "eventDate": "2026-11-19T03:00:00Z",
                "publishDate": "2026-11-19T03:01:00Z",
                "publishAttemptCount": 2,
                "data": {
                    "userId": "other-user-456",
                },
            },
        }

        with patch.object(
            ebay_api,
            "_verify_ebay_signature",
            return_value=True,
        ):
            response = self.client.post(
                "/api/v1/integrations/ebay/account-deletion",
                json=retry_payload,
                headers={"X-EBAY-SIGNATURE": "fake-valid-signature"},
            )

        self.assertEqual(response.status_code, 204)

        db = TestSession()

        notification = db.query(EbayNotification).filter_by(
            notification_id="test-notification-failed"
        ).one()

        listing = db.query(EbayListing).filter_by(
            ebay_item_id="other-item-002"
        ).one()

        seller = db.query(EbaySeller).filter_by(
            id=listing.seller_id
        ).one()

        self.assertEqual(notification.status, "processed")
        self.assertEqual(notification.attempt_count, 2)
        self.assertIsNone(notification.last_error)
        self.assertIsNone(seller.ebay_user_id)
        self.assertIsNone(listing.title)
        self.assertEqual(listing.listing_status, "anonymized")

        self.assertEqual(
            db.query(EbayNotification).filter_by(
                notification_id="test-notification-failed"
            ).count(),
            1,
        )

        db.close()

        print("PASS: Failed notification successfully retried.")

    def test_09_notification_id_reuse_rejected(self):
        modified_payload = {
            "metadata": {
                "topic": "MARKETPLACE_ACCOUNT_DELETION",
            },
            "notification": {
                "notificationId": "test-notification-001",
                "eventDate": "2026-11-19T03:00:00Z",
                "publishDate": "2026-11-19T03:01:00Z",
                "publishAttemptCount": 1,
                "data": {
                    "userId": "third-user-789",
                },
            },
        }

        with patch.object(
            ebay_api,
            "_verify_ebay_signature",
            return_value=True,
        ):
            response = self.client.post(
                "/api/v1/integrations/ebay/account-deletion",
                json=modified_payload,
                headers={"X-EBAY-SIGNATURE": "fake-valid-signature"},
            )

        self.assertEqual(response.status_code, 409)

        db = TestSession()

        notification = db.query(EbayNotification).filter_by(
            notification_id="test-notification-001"
        ).one()

        seller = db.query(EbaySeller).filter_by(
            ebay_user_id="third-user-789"
        ).one()

        listing = db.query(EbayListing).filter_by(
            ebay_item_id="third-item-003"
        ).one()

        self.assertEqual(notification.status, "processed")
        self.assertEqual(seller.username, "third-seller")
        self.assertEqual(seller.status, "active")
        self.assertEqual(listing.title, "Hot Wheels Third Car")
        self.assertEqual(listing.listing_status, "active")
        self.assertIsNone(listing.anonymized_at)

        self.assertEqual(
            db.query(EbayNotification).filter_by(
                notification_id="test-notification-001"
            ).count(),
            1,
        )

        db.close()

        print("PASS: Reused notification ID with modified payload rejected.")

    def test_integrity_conflict_rechecks_payload_and_processing_status(self):
        payload = copy.deepcopy(PAYLOAD)
        payload["notification"]["notificationId"] = "test-notification-race"
        normalized = copy.deepcopy(payload)
        normalized["notification"].pop("publishAttemptCount", None)
        payload_hash = hashlib.sha256(
            json.dumps(
                normalized,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()

        class FakeQuery:
            def __init__(self, db):
                self.db = db

            def filter_by(self, **_filters):
                return self

            def first(self):
                self.db.query_count += 1
                return None if self.db.query_count == 1 else self.db.existing

        class ConflictSession:
            def __init__(self, existing):
                self.existing = existing
                self.query_count = 0

            def query(self, _model):
                return FakeQuery(self)

            def add(self, _record):
                pass

            def flush(self):
                raise IntegrityError("INSERT", {}, Exception("duplicate notification ID"))

            def rollback(self):
                pass

        async def make_request():
            body = json.dumps(payload).encode("utf-8")
            delivered = False

            async def receive():
                nonlocal delivered
                if delivered:
                    return {"type": "http.disconnect"}
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}

            return Request(
                {
                    "type": "http",
                    "asgi": {"version": "3.0"},
                    "http_version": "1.1",
                    "method": "POST",
                    "scheme": "http",
                    "path": "/api/v1/integrations/ebay/account-deletion",
                    "raw_path": b"/api/v1/integrations/ebay/account-deletion",
                    "query_string": b"",
                    "headers": [(b"x-ebay-signature", b"test-signature")],
                    "client": ("127.0.0.1", 12345),
                    "server": ("127.0.0.1", 8000),
                },
                receive,
            )

        cases = [
            ("different-hash", "processed", 409),
            (payload_hash, "processed", 204),
            (payload_hash, "failed", 503),
        ]
        with patch.object(ebay_api, "_verify_ebay_signature", return_value=True):
            for existing_hash, status, expected_status in cases:
                existing = EbayNotification(
                    notification_id="test-notification-race",
                    topic="MARKETPLACE_ACCOUNT_DELETION",
                    payload_sha256=existing_hash,
                    status=status,
                )
                db = ConflictSession(existing)
                request = asyncio.run(make_request())
                if expected_status == 204:
                    response = asyncio.run(
                        ebay_api.receive_account_deletion_notification(request, db)
                    )
                    self.assertEqual(response.status_code, expected_status)
                else:
                    with self.assertRaises(HTTPException) as exc:
                        asyncio.run(
                            ebay_api.receive_account_deletion_notification(request, db)
                        )
                    self.assertEqual(exc.exception.status_code, expected_status)

        print("PASS: Concurrent ID conflict rechecks payload hash and final status.")

if __name__ == "__main__":
    unittest.main(verbosity=2)
