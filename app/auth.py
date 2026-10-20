"""Account authentication with PostgreSQL-backed sessions and rate limits."""

from __future__ import annotations
import asyncio
import hashlib
import hmac
import os
import secrets
import uuid
from datetime import timedelta
from fastapi import Depends, HTTPException, Request
from fastapi.security.utils import get_authorization_scheme_param
from sqlalchemy.exc import IntegrityError
from . import store

COOKIE_NAME = "somas_session"
SESSION_SECONDS = 7 * 24 * 3600
HASH_ITERATIONS = 600_000


def hash_password(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf8"), salt, HASH_ITERATIONS)


async def throttle(namespace, identity, limit, seconds=900):
    now = store.stamp()
    key = hashlib.sha256(
        f"{namespace}:{identity}:{int(now.timestamp()) // seconds}".encode()
    ).hexdigest()
    count = await store.throttle(key, now + timedelta(seconds=seconds * 2))
    if count > limit:
        raise HTTPException(
            429,
            "Too many requests. Try again later.",
            headers={"Retry-After": str(seconds)},
        )


def client_identity(request):
    if getattr(request.state, "trusted_gateway", False):
        return request.headers.get("x-somas-client-ip", "unknown")
    return request.client.host if request.client else "unknown"


async def register(email, display_name, password):
    salt = secrets.token_bytes(24)
    digest = await asyncio.to_thread(hash_password, password, salt)
    uid = "usr_" + uuid.uuid4().hex
    try:
        await store.register_user(
            uid, email.strip().lower(), display_name.strip(), salt, digest
        )
    except IntegrityError as exc:
        if getattr(exc.orig, "sqlstate", None) != "23505":
            raise
        raise HTTPException(409, "Account already exists for this email address")
    return {
        "id": uid,
        "email": email.strip().lower(),
        "display_name": display_name.strip(),
    }


async def user_by_id(uid):
    return await store.user_by_id(uid)


async def verify_credentials(email, password, ip="local"):
    email = email.strip().lower()
    await throttle("login-ip", ip, 40)
    await throttle("login-email", email, 10)
    row = await store.user_credentials(email)
    salt = bytes(row["password_salt"]) if row else bytes.fromhex("28" * 24)
    expected = bytes(row["password_hash"]) if row else bytes.fromhex("29" * 32)
    digest = await asyncio.to_thread(hash_password, password, salt)
    if not row or not hmac.compare_digest(digest, expected):
        raise HTTPException(401, "Invalid email or password")
    return row


async def issue_session(uid, expected_version=None):
    token = secrets.token_urlsafe(48)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    csrf = secrets.token_urlsafe(32)
    now = store.stamp()
    if not await store.issue_session(
        uid,
        token_hash,
        csrf,
        now,
        now + timedelta(seconds=SESSION_SECONDS),
        expected_version,
    ):
        raise HTTPException(401, "Credentials changed. Please sign in again.")
    return token, csrf


async def session_for(token):
    if not token:
        return None
    return await store.session_for(hashlib.sha256(token.encode()).hexdigest())


async def session_from_request(request: Request):
    header = request.headers.get("authorization", "")
    scheme, token = get_authorization_scheme_param(header)
    if header:
        if scheme.lower() != "bearer":
            raise HTTPException(401, "Use Bearer authentication")
        return await session_for(token), False
    return await session_for(request.cookies.get(COOKIE_NAME)), True


async def current_auth(request: Request):
    session, via_cookie = await session_from_request(request)
    if not session:
        raise HTTPException(401, "Please sign in")
    if via_cookie and request.method.upper() not in ("GET", "HEAD", "OPTIONS"):
        submitted = request.headers.get("x-csrf-token", "")
        if not hmac.compare_digest(
            submitted.encode("utf8"), session["csrf"].encode("utf8")
        ):
            raise HTTPException(403, "Missing or invalid CSRF token")
    user = await user_by_id(session["user_id"])
    if not user:
        raise HTTPException(401, "Account no longer exists")
    await throttle("account-read", user["id"], 120, 60)
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        await throttle("account-write", user["id"], 20, 60)
    return {"user": user, "session": session, "via_cookie": via_cookie}


async def current_user(identity=Depends(current_auth)):
    return identity["user"]


async def destroy_session(session):
    await store.destroy_session(session["user_id"], session["token_hash"])


def secure_cookies(request):
    # Do not trust arbitrary X-Forwarded-Proto headers.
    return (
        os.getenv("VERCEL") == "1"
        or request.url.scheme == "https"
        or os.getenv("SOMAS_SECURE_COOKIES", "").lower() in ("true", "1")
    )


def set_cookie(response, request: Request, token):
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=SESSION_SECONDS,
        httponly=True,
        secure=secure_cookies(request),
        samesite="strict",
        path="/",
    )
