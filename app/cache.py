"""Caches of the API and HTTP caching of read-only answers.

Two levels:
1. In memory (LRUCache): reference data that almost never changes (catalog, starter templates) and
   each user's settings, so those requests skip PostgreSQL. Render runs a single instance, so an
   in-process cache is enough; with several instances, writes would only clear their own copy.
2. HTTP (ETag + Cache-Control): the browser keeps the answer and asks "did it change?" with
   If-None-Match; when it did not, the API answers 304 with no body.

Private data (projects, runs, tokens) is never cached here and keeps Cache-Control: no-store.
"""
import hashlib
import json
import os

from fastapi import Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.structures import LRUCache


def _ttl(name: str, default: int) -> int:
    return int(os.environ.get(name, str(default)))


# Reference data: the same for everybody and only changed by migrations.
reference_cache = LRUCache(capacity=64, ttl_seconds=_ttl("CACHE_REFERENCE_TTL", 600))
# Settings of each user: cleared when that user saves them.
settings_cache = LRUCache(capacity=2048, ttl_seconds=_ttl("CACHE_SETTINGS_TTL", 300))

CACHES = {"reference": reference_cache, "settings": settings_cache}


def clear_all() -> None:
    """Empties every cache (tests, or after running migrations in the same process)."""
    for cache in CACHES.values():
        cache.clear()


def stats() -> dict:
    return {name: cache.stats() for name, cache in CACHES.items()}


# ---------------------------------------------------------------------- HTTP caching

PUBLIC = "public, max-age=300, stale-while-revalidate=86400"
PRIVATE = "private, max-age=60, must-revalidate"


def etag_for(data) -> str:
    """Strong ETag: a hash of the canonical JSON of the answer."""
    body = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str).encode()
    return '"' + hashlib.sha256(body).hexdigest()[:32] + '"'


def cached_json(request: Request, data, cache_control: str = PUBLIC) -> Response:
    """JSON answer with ETag and Cache-Control; 304 without a body when the browser already has it."""
    data = jsonable_encoder(data)  # numeric columns come as Decimal, dates as datetime
    tag = etag_for(data)
    # A private answer depends on who asks: shared caches must keep one copy per token.
    vary = "Authorization, Accept-Encoding" if cache_control.startswith("private") else "Accept-Encoding"
    headers = {"ETag": tag, "Cache-Control": cache_control, "Vary": vary}
    if etag_matches(request.headers.get("if-none-match", ""), tag):
        return Response(status_code=304, headers=headers)
    return JSONResponse(data, headers=headers)


def etag_matches(sent: str, tag: str) -> bool:
    """If-None-Match uses the weak comparison (RFC 9110, 13.1.2): W/"x" matches "x".

    In production Cloudflare (in front of Render) compresses the answer and turns
    our strong tag into a weak one, so the browser sends W/"..." back. Comparing
    only the opaque part makes those requests answer 304 instead of the whole body.
    """
    if sent.strip() == "*":
        return True

    def opaque(value: str) -> str:
        value = value.strip()
        return value[2:] if value.startswith("W/") else value

    return opaque(tag) in (opaque(t) for t in sent.split(",") if t.strip())
