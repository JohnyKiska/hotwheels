import base64
import hashlib
import json
import os
import time
from urllib.parse import quote

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import APIRouter, HTTPException, Query, Request

from datetime import datetime, timezone

from fastapi import Depends, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .db import get_db
from .models import EbaySeller, EbayListing, EbayNotification

from . import config


router = APIRouter(
    prefix="/api/v1/integrations/ebay",
    tags=["eBay Notifications"],
)

# Кеши в памяти процесса
_oauth_cache = {
    "sandbox": {"token": None, "expires_at": 0},
    "production": {"token": None, "expires_at": 0},
}

_public_key_cache = {
    "sandbox": {},
    "production": {},
}


def _get_ebay_config():
    environment = os.getenv(
        "HW_EBAY_ENVIRONMENT", "sandbox"
    ).lower()

    if environment not in ("sandbox", "production"):
        raise RuntimeError("Invalid eBay environment.")

    prefix = (
        "HW_EBAY_SANDBOX"
        if environment == "sandbox"
        else "HW_EBAY_PRODUCTION"
    )

    client_id = os.getenv(f"{prefix}_CLIENT_ID")
    client_secret = os.getenv(f"{prefix}_CLIENT_SECRET")

    if not client_id or not client_secret:
        raise RuntimeError("eBay credentials are missing.")

    host = (
        "https://api.sandbox.ebay.com"
        if environment == "sandbox"
        else "https://api.ebay.com"
    )

    return host, client_id, client_secret



def _get_oauth_token():
    environment = os.getenv(
        "HW_EBAY_ENVIRONMENT", "sandbox"
    ).lower()

    if environment not in _oauth_cache:
        raise RuntimeError("Invalid eBay environment.")

    cache = _oauth_cache[environment]
    now = time.time()

    if (
        cache["token"]
        and cache["expires_at"] > now + 60
    ):
        return cache["token"]

    host, client_id, client_secret = _get_ebay_config()

    credentials = base64.b64encode(
        f"{client_id}:{client_secret}".encode("utf-8")
    ).decode("ascii")

    response = requests.post(
        f"{host}/identity/v1/oauth2/token",
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "client_credentials",
            "scope": "https://api.ebay.com/oauth/api_scope",
        },
        timeout=15,
    )

    response.raise_for_status()
    data = response.json()

    token = data["access_token"]
    expires_in = int(data.get("expires_in", 7200))

    cache["token"] = token
    cache["expires_at"] = now + expires_in

    return token




def _get_public_key(key_id):
    environment = os.getenv(
        "HW_EBAY_ENVIRONMENT", "sandbox"
    ).lower()

    if environment not in _public_key_cache:
        raise RuntimeError("Invalid eBay environment.")

    cache = _public_key_cache[environment]
    now = time.time()

    cached = cache.get(key_id)

    if cached and cached["expires_at"] > now:
        return cached["key_data"]

    host, _, _ = _get_ebay_config()
    token = _get_oauth_token()

    response = requests.get(
        f"{host}/commerce/notification/v1/public_key/{quote(key_id, safe='')}",
        headers={
            "Authorization": f"Bearer {token}",
        },
        timeout=15,
    )

    response.raise_for_status()
    key_data = response.json()

    cache[key_id] = {
        "key_data": key_data,
        "expires_at": now + 3600,
    }

    return key_data





def _verify_ebay_signature(signature_header, payload):
    try:
        decoded_header = base64.b64decode(
            signature_header,
            validate=True,
        )
        signature_info = json.loads(decoded_header)

        key_id = signature_info["kid"]
        signature = base64.b64decode(
            signature_info["signature"],
            validate=True,
        )

        if signature_info.get("alg", "").lower() != "ecdsa":
            return False

        digest_name = signature_info["digest"].upper()

        key_data = _get_public_key(key_id)

        response_digest = key_data.get("digest")
        if response_digest and response_digest.upper() != digest_name:
            return False

        key_value = key_data["key"].strip()

        if "-----BEGIN PUBLIC KEY-----" in key_value:
            key_value = key_value.replace(
                "-----BEGIN PUBLIC KEY-----",
                "-----BEGIN PUBLIC KEY-----\n",
            ).replace(
                "-----END PUBLIC KEY-----",
                "\n-----END PUBLIC KEY-----",
            )

            public_key = serialization.load_pem_public_key(
                key_value.encode("ascii")
            )
        else:
            public_key_bytes = base64.b64decode(
                key_value,
                validate=True,
            )
            public_key = serialization.load_der_public_key(
                public_key_bytes
            )

        if not isinstance(public_key, ec.EllipticCurvePublicKey):
            return False

        digest_map = {
            "SHA1": hashes.SHA1,
            "SHA256": hashes.SHA256,
            "SHA384": hashes.SHA384,
            "SHA512": hashes.SHA512,
        }

        digest_class = digest_map.get(digest_name)

        if digest_class is None:
            return False

        message = json.dumps(
            payload,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")

        public_key.verify(
            signature,
            message,
            ec.ECDSA(digest_class()),
        )

        return True

    except requests.RequestException:
        raise
    except Exception:
        return False




@router.get("/account-deletion")
def verify_account_deletion_endpoint(
    challenge_code: str = Query(min_length=1),
):
    verification_token = os.getenv(
        "HW_EBAY_DELETION_VERIFICATION_TOKEN"
    )
    endpoint_url = os.getenv(
        "HW_EBAY_DELETION_ENDPOINT_URL"
    )

    if not verification_token or not endpoint_url:
        raise HTTPException(
            status_code=503,
            detail="eBay notification configuration is missing.",
        )

    if not 32 <= len(verification_token) <= 80:
        raise HTTPException(
            status_code=500,
            detail="Invalid verification token length.",
        )

    allowed = set(
        "abcdefghijklmnopqrstuvwxyz"
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        "0123456789_-"
    )

    if not all(char in allowed for char in verification_token):
        raise HTTPException(
            status_code=500,
            detail="Invalid verification token characters.",
        )

    payload = (
        challenge_code
        + verification_token
        + endpoint_url
    )

    challenge_response = hashlib.sha256(
        payload.encode("utf-8")
    ).hexdigest()

    return {"challengeResponse": challenge_response}


def _parse_ebay_datetime(value):
    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except (ValueError, TypeError, AttributeError):
        return None


def _utc_now():
    return datetime.now(timezone.utc)




@router.post("/account-deletion")
async def receive_account_deletion_notification(
    request: Request,
    db: Session = Depends(get_db),
):
    signature_header = request.headers.get("X-EBAY-SIGNATURE")

    if not signature_header:
        raise HTTPException(
            status_code=412,
            detail="Missing eBay signature.",
        )

    # Читаем исходное тело, чтобы вычислить его хеш.
    raw_body = await request.body()

    try:
        payload = json.loads(raw_body)
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Invalid JSON payload.",
        )

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=400,
            detail="Invalid notification structure.",
        )

    # Подпись проверяется ДО любых операций с БД.
    try:
        is_valid = _verify_ebay_signature(
            signature_header,
            payload,
        )
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Unable to verify eBay signature.",
        )

    if not is_valid:
        raise HTTPException(
            status_code=412,
            detail="Invalid eBay signature.",
        )

    metadata = payload.get("metadata") or {}
    notification = payload.get("notification") or {}
    data = notification.get("data") or {}

    if not all(
        isinstance(item, dict)
        for item in (metadata, notification, data)
    ):
        raise HTTPException(
            status_code=400,
            detail="Invalid notification structure.",
        )

    notification_id = notification.get("notificationId")
    topic = metadata.get("topic")

    if not notification_id or not topic:
        raise HTTPException(
            status_code=400,
            detail="Missing notification ID or topic.",
        )

    notification_id = str(notification_id)
    topic = str(topic)

    if len(notification_id) > 180 or len(topic) > 100:
        raise HTTPException(
            status_code=400,
            detail="Invalid notification field length.",
        )

    # Хешируем содержимое без счётчика повторных доставок.
    normalized_payload = dict(payload)
    normalized_notification = dict(notification)
    normalized_notification.pop("publishAttemptCount", None)
    normalized_payload["notification"] = normalized_notification

    normalized_body = json.dumps(
        normalized_payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")

    payload_hash = hashlib.sha256(normalized_body).hexdigest()

    existing = db.query(EbayNotification).filter_by(
        notification_id=notification_id
    ).first()

    if existing:
        # Один ID не должен соответствовать разным payload.
        if existing.payload_sha256 != payload_hash:
            raise HTTPException(
                status_code=409,
                detail="Notification ID reused with different payload.",
            )

        if existing.status in ("processed", "ignored"):
            return Response(status_code=204)

        if existing.status not in ("failed", "received"):
            raise HTTPException(
                status_code=503,
                detail="Notification has an unexpected status.",
            )

    now = _utc_now()

    event_date = _parse_ebay_datetime(
        notification.get("eventDate")
    )
    publish_date = _parse_ebay_datetime(
        notification.get("publishDate")
    )

    try:
        if existing:
            record = existing
            record.status = "received"
            record.processed_at = None
            record.last_error = None
            record.attempt_count = int(
                notification.get("publishAttemptCount", 0)
            )
            record.payload_sha256 = payload_hash
            record.event_date = event_date
            record.publish_date = publish_date
            record.signature_valid = True
        else:
            record = EbayNotification(
                notification_id=notification_id,
                topic=topic,
                event_date=event_date,
                publish_date=publish_date,
                received_at=now,
                status="received",
                signature_valid=True,
                attempt_count=int(
                    notification.get("publishAttemptCount", 0)
                ),
                payload_sha256=payload_hash,
            )

            db.add(record)

        db.flush()


        # Не обрабатываем посторонние типы уведомлений.
        if "ACCOUNT_DELETION" not in topic.upper():
            record.status = "ignored"
            record.processed_at = _utc_now()
            db.commit()
            return Response(status_code=204)

        ebay_user_id = data.get("userId")

        if ebay_user_id:
            seller = db.query(EbaySeller).filter_by(
                ebay_user_id=str(ebay_user_id)
            ).first()

            if seller:
                # Удаляем персональные данные продавца.
                seller.ebay_user_id = None
                seller.username = None
                seller.display_name = None
                seller.profile_url = None
                seller.status = "anonymized"
                seller.deleted_at = _utc_now()

                # Убираем потенциально персональные сведения
                # из связанных объявлений.
                listings = db.query(EbayListing).filter_by(
                    seller_id=seller.id
                ).all()

                for listing in listings:
                    listing.title = None
                    listing.item_url = None
                    listing.listing_status = "anonymized"
                    listing.anonymized_at = _utc_now()

        record.status = "processed"
        record.processed_at = _utc_now()

        db.commit()

        return Response(status_code=204)

    except IntegrityError:
        db.rollback()

        # Возможно, параллельно пришёл тот же notificationId.
        existing = db.query(EbayNotification).filter_by(
            notification_id=notification_id
        ).first()

        if existing:
            if existing.payload_sha256 != payload_hash:
                raise HTTPException(
                    status_code=409,
                    detail="Notification ID reused with different payload.",
                )
            if existing.status not in ("processed", "ignored"):
                raise HTTPException(
                    status_code=503,
                    detail="Notification has not completed processing.",
                )
            return Response(status_code=204)

        raise HTTPException(
            status_code=503,
            detail="Notification database conflict.",
        )


    except Exception:
        db.rollback()

        # Сохраняем информацию о неудачной обработке.
        try:
            failed_record = db.query(EbayNotification).filter_by(
                notification_id=notification_id
            ).first()

            if failed_record:
                failed_record.status = "failed"
                failed_record.processed_at = None
                failed_record.last_error = "Notification processing failed."
            else:
                try:
                    attempt_count = int(
                        notification.get("publishAttemptCount", 0)
                    )
                except (ValueError, TypeError):
                    attempt_count = 0

                failed_record = EbayNotification(
                    notification_id=notification_id,
                    topic=topic,
                    event_date=event_date,
                    publish_date=publish_date,
                    received_at=now,
                    status="failed",
                    signature_valid=True,
                    attempt_count=attempt_count,
                    payload_sha256=payload_hash,
                    last_error="Notification processing failed.",
                )
                db.add(failed_record)

            db.commit()

        except Exception:
            db.rollback()

        raise HTTPException(
            status_code=503,
            detail="Notification processing failed.",
        )
