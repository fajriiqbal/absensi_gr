from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
from django.conf import settings
from jwt import InvalidTokenError


TOKEN_TTL_SECONDS = 15
TV_PREFIX = "MTS-TV-DYNAMIC:"
PRINTABLE_PREFIX = "MTS-PRINTABLE-QR:"
GURU_PREFIX = "MTS-GURU-QR:"


def generate_dynamic_qr_token(now=None):
    issued_at = now or datetime.now(timezone.utc)
    payload = {
        "iss": "absensi-guru",
        "aud": "school-attendance",
        "typ": "school-tv-qr",
        "jti": str(uuid4()),
        "iat": issued_at,
        "exp": issued_at + timedelta(seconds=TOKEN_TTL_SECONDS),
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")
    return f"{TV_PREFIX}{token}"


def verify_dynamic_qr_token(token, now=None):
    try:
        options = {"verify_exp": now is None}
        claims = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=["HS256"],
            audience="school-attendance",
            issuer="absensi-guru",
            options=options,
        )
        if claims.get("typ") != "school-tv-qr":
            return {"error": "Jenis QR dinamis tidak valid."}, False
        if now is not None and claims.get("exp", 0) <= now.timestamp():
            return {"error": "QR dinamis sudah kedaluwarsa."}, False
        return claims, True
    except InvalidTokenError:
        return {"error": "QR dinamis tidak valid atau sudah kedaluwarsa."}, False


def generate_teacher_qr_token(user, now=None):
    issued_at = now or datetime.now(timezone.utc)
    payload = {
        "iss": "absensi-guru",
        "aud": "kiosk-attendance",
        "typ": "teacher-kiosk-qr",
        "sub": str(user.pk),
        "jti": str(uuid4()),
        "iat": issued_at,
        "exp": issued_at + timedelta(seconds=45),
    }
    return f"{GURU_PREFIX}{jwt.encode(payload, settings.SECRET_KEY, algorithm='HS256')}"


def verify_teacher_qr_token(token):
    try:
        claims = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=["HS256"],
            audience="kiosk-attendance",
            issuer="absensi-guru",
        )
        if claims.get("typ") != "teacher-kiosk-qr":
            return {"error": "QR guru tidak valid."}, False
        return claims, True
    except InvalidTokenError:
        return {"error": "QR guru tidak valid atau sudah kedaluwarsa."}, False