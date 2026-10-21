"""ASGI guards run before body parsing and never trust arbitrary forwarded headers."""

import asyncio
import hmac
import json
import logging
import os
import time

MAX_BODY = 32768
logger = logging.getLogger("somas.requests")


class SecurityMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith("/api/"):
            return await self.app(scope, receive, send)
        headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}

        async def reject(status, detail):
            body = json.dumps({"detail": detail}).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": status,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"cache-control", b"no-store"),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})

        secret = os.getenv("SOMAS_PROXY_SECRET", "")
        trusted = bool(secret) and hmac.compare_digest(
            headers.get("x-somas-proxy-secret", "").encode("utf8"),
            secret.encode("utf8"),
        )
        if secret and not trusted:
            return await reject(403, "API gateway required")
        scope.setdefault("state", {})["trusted_gateway"] = trusted
        allowed = {
            v.strip()
            for v in os.getenv(
                "SOMAS_ALLOWED_ORIGINS",
                "http://localhost:8788,http://127.0.0.1:8788,http://localhost:8000,http://127.0.0.1:8000",
            ).split(",")
            if v.strip()
        }
        origin = headers.get("origin")
        unsafe = scope["method"] not in ("GET", "HEAD", "OPTIONS")
        if (origin and origin not in allowed) or (unsafe and not origin):
            return await reject(403, "Origin is not allowed")
        if headers.get("sec-fetch-site") == "cross-site":
            return await reject(403, "Cross-site request rejected")
        try:
            if int(headers.get("content-length", "0")) > MAX_BODY:
                return await reject(413, "Request body too large")
        except ValueError:
            return await reject(400, "Invalid content length")
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > MAX_BODY:
                return await reject(413, "Request body too large")
            if not message.get("more_body"):
                break
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        status = 500
        started = False

        async def safe_send(message):
            nonlocal status, started
            if message["type"] == "http.response.start":
                status = message["status"]
                started = True
            await send(message)

        began = time.monotonic()
        try:
            await asyncio.wait_for(self.app(scope, replay, safe_send), timeout=130)
        except TimeoutError:
            if not started:
                await reject(504, "Operation timed out. Check history before retrying.")
        finally:
            # Never log URL queries, request bodies, email, tokens, IP, or upstream errors.
            logger.info(
                "request_finished status=%s duration_ms=%s",
                status,
                int((time.monotonic() - began) * 1000),
            )
