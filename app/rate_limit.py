"""Per-client request limits (sliding window), kept in memory.

Login, registration and the AI are expensive or sensitive, so they get much
lower limits than the rest of the API. Over the limit the API answers 429 with
a Retry-After header. One instance only: several instances would each count
on their own (use a shared store such as Redis if the service is scaled out).
"""
import ipaddress
import json
import math
import os
import threading
import time
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    """At most `limit` requests per `window` seconds for paths starting with `prefix`."""

    name: str
    prefix: str
    limit: int
    window: float
    methods: tuple = ("POST",)

    def matches(self, method: str, path: str) -> bool:
        return path.startswith(self.prefix) and (not self.methods or method in self.methods)


DEFAULT_RULES = (
    Rule("register", "/auth/register", 5, 60),
    Rule("login", "/auth/login", 10, 60),
    Rule("refresh", "/auth/refresh", 30, 60),
    # One challenge per account request; generous for retries, but not a free RSA workload.
    Rule("challenge", "/auth/challenge", 60, 60, methods=("GET",)),
    Rule("password", "/auth/password", 5, 300),
    # Every picture goes through the full security check (sprite_scan.py): few per minute.
    Rule("sprites", "/me/sprites", 10, 60),
    Rule("ai", "/projects/", 20, 60),  # only paths that contain /ai, see _rules_for
    Rule("global", "/", 300, 60, methods=()),
)


class SlidingWindowLimiter:
    """Remembers the time of each request per key and drops the old ones."""

    # Every this many requests, forget clients that have been quiet for a while,
    # so the table does not grow with every address that ever called the API.
    SWEEP_EVERY = 1000

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._hits: dict = {}
        self._lock = threading.Lock()
        self._calls = 0
        self._longest_window = 0.0

    def hit(self, key: str, limit: int, window: float) -> float:
        """Record a request. Returns 0 if allowed, or the seconds to wait if not."""
        now = self._clock()
        with self._lock:
            self._longest_window = max(self._longest_window, window)
            self._calls += 1
            if self._calls % self.SWEEP_EVERY == 0:
                self._sweep(now)
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= now - window:
                hits.popleft()
            if len(hits) >= limit:
                return max(0.0, hits[0] + window - now)
            hits.append(now)
            return 0.0

    def _sweep(self, now: float) -> None:
        """Drop the keys whose newest request is older than the longest window."""
        for key in [k for k, hits in self._hits.items() if not hits or hits[-1] <= now - self._longest_window]:
            del self._hits[key]

    def size(self) -> int:
        """How many clients are being tracked (for tests and monitoring)."""
        with self._lock:
            return len(self._hits)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


# Headers an edge network sets to the visitor's address. On Render the edge is
# Cloudflare: it overwrites True-Client-IP and refuses requests that bring their
# own CF-Connecting-IP, so a client cannot fake them there. Off such an edge
# anybody can send them, so they are only read when trust_edge_header is on.
EDGE_HEADERS = (b"cf-connecting-ip", b"true-client-ip")


def _valid_ip(value: str) -> str | None:
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


def client_ip(scope, trusted_proxy_hops: int = 0, trust_edge_header: bool = False) -> str:
    """The caller's address. Behind a proxy (Render, Nginx) X-Forwarded-For is
    only trusted for the number of proxies we know are in front of us: clients
    can write anything at its start, so it is read from the end."""
    headers = scope.get("headers", [])
    if trust_edge_header:
        for wanted in EDGE_HEADERS:
            for name, value in headers:
                if name == wanted:
                    ip = _valid_ip(value.decode("latin-1"))
                    if ip:
                        return ip
    if trusted_proxy_hops > 0:
        for name, value in headers:
            if name == b"x-forwarded-for":
                addresses = [a.strip() for a in value.decode("latin-1").split(",") if a.strip()]
                if len(addresses) >= trusted_proxy_hops:
                    ip = _valid_ip(addresses[-trusted_proxy_hops])
                    if ip:
                        return ip
    client = scope.get("client")
    return client[0] if client else "unknown"


def proxy_settings(environ=None) -> tuple:
    """(trusted proxy hops, trust the edge header) for this deployment.

    Render sets RENDER=true. There the visitor comes through Cloudflare and two
    proxies, so X-Forwarded-For ends with "visitor, cloudflare, render" and the
    edge headers are reliable. Elsewhere nothing is trusted unless configured.
    """
    environ = os.environ if environ is None else environ
    on_render = environ.get("RENDER", "").lower() == "true"
    hops_value = environ.get("TRUSTED_PROXY_HOPS", "").strip()
    hops = int(hops_value) if hops_value.isdigit() else (3 if on_render else 0)
    edge_value = environ.get("TRUST_EDGE_IP_HEADER", "").strip().lower()
    edge = edge_value in ("1", "true", "yes") if edge_value else on_render
    return hops, edge


class RateLimitMiddleware:
    """ASGI middleware that applies the rules to every HTTP request."""

    def __init__(self, app, limiter: SlidingWindowLimiter, rules=DEFAULT_RULES, trusted_proxy_hops: int = 0,
                 multiplier: int = 1, trust_edge_header: bool = False):
        self.app = app
        self.limiter = limiter
        self.rules = rules
        self.trusted_proxy_hops = trusted_proxy_hops
        self.trust_edge_header = trust_edge_header
        # Only automated test environments raise this (config.py forbids it in production).
        self.multiplier = max(1, multiplier)

    def _rules_for(self, method: str, path: str):
        for rule in self.rules:
            if rule.name == "ai" and "/ai" not in path:
                continue
            if rule.matches(method, path):
                yield rule

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] == "OPTIONS":
            await self.app(scope, receive, send)
            return
        ip = client_ip(scope, self.trusted_proxy_hops, self.trust_edge_header)
        for rule in self._rules_for(scope["method"], scope["path"]):
            wait = self.limiter.hit(f"{rule.name}:{ip}", rule.limit * self.multiplier, rule.window)
            if wait:
                await _too_many_requests(send, math.ceil(wait))
                return
        await self.app(scope, receive, send)


async def _too_many_requests(send, retry_after: int) -> None:
    body = json.dumps({"detail": "Too many requests, slow down"}).encode()
    await send({
        "type": "http.response.start",
        "status": 429,
        "headers": [
            (b"content-type", b"application/json"),
            (b"retry-after", str(max(1, retry_after)).encode()),
            (b"content-length", str(len(body)).encode()),
        ],
    })
    await send({"type": "http.response.body", "body": body})
