# Cache

The API caches at two levels. Private data (projects, runs, tokens, profile) is never cached and
keeps `Cache-Control: no-store`.

## 1. In memory: `LRUCache` (`app/structures/lru_cache.py`)

Hand-written like the other structures: a dictionary maps each key to a node of a doubly linked
list ordered from the most to the least recently used.

| Operation | Cost | Notes |
|---|---|---|
| `get(key)` | O(1) | Moves the entry to the front; an expired entry counts as absent and is removed |
| `put(key, value, ttl)` | O(1) | When full, evicts the least recently used entry (right before the tail) |
| `delete(key)`, `clear()` | O(1) | |
| `get_or_load(key, loader)` | O(1) + loader | Calls the loader only on a miss |
| `purge_expired()` | O(n) | Walks the list once |

A lock protects every operation (FastAPI runs synchronous routes in a thread pool). Render runs a
single instance of the API, so an in-process cache is enough; with several instances each one
would keep its own copy and a shared cache (Redis) would be needed.

Caches in `app/cache.py`:

| Cache | What it holds | Lifetime | Invalidation |
|---|---|---|---|
| `reference_cache` | `/catalog/*` (kinds, enemies, characters, textures) and `/projects/templates` | `CACHE_REFERENCE_TTL` (600 s) | Only migrations change this data; it expires on its own |
| `settings_cache` | `/me/settings` of each user | `CACHE_SETTINGS_TTL` (300 s) | Write-through: `PUT /me/settings` stores the new values at once |

The catalog uses a lazy connection (`LazyConnection` in `app/database.py`): when the answer comes
from memory no connection to PostgreSQL is opened at all.

## 2. HTTP: ETag and Cache-Control

`cached_json()` adds a strong `ETag` (SHA-256 of the JSON) and answers **304 Not Modified** with no
body when the browser sends the same tag in `If-None-Match`.

| Route | Cache-Control |
|---|---|
| `/catalog/*` | `public, max-age=300, stale-while-revalidate=86400` |
| `/projects/templates` | `private, max-age=60, must-revalidate` + `Vary: Authorization` |
| everything else | `no-store` |

In production Cloudflare (in front of Render) compresses the answers and turns the strong tag into
a weak one (`W/"..."`), which is what the browser then sends back. `etag_matches()` uses the weak
comparison that RFC 9110 asks for in `If-None-Match`, so those requests also get their 304.

## 3. Database connections

The API keeps a small pool of open connections (`psycopg_pool`, `app/database.py`): a request
borrows one and gives it back, instead of opening a new TLS connection to Supabase every time
(about 100 ms saved per request). `DB_POOL_MIN` / `DB_POOL_MAX` set its size (1 and 5 by default,
below the free session pooler's limit); `DB_POOL=0` goes back to one connection per request.
