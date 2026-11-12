import os
import threading

import psycopg
from psycopg.rows import dict_row

# Options of every connection. prepare_threshold=None disables server-side prepared
# statements, which Supabase's transaction pooler (pgbouncer) does not support.
CONNECT_OPTIONS = {"row_factory": dict_row, "prepare_threshold": None}


def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return url


def get_connection():
    """Open a new connection to the database configured in DATABASE_URL.

    Used by the migrations and maintenance scripts, which run once. The API itself takes its
    connections from the pool (see pooled_connection).
    """
    return psycopg.connect(database_url(), **CONNECT_OPTIONS)


# ------------------------------------------------------------------ connection pool
#
# Opening a connection to Supabase means a TCP and a TLS handshake plus authentication: about
# 100 ms before the first query, on every request. The pool keeps a few connections open and
# lends them out, so a request only pays for its queries. It is created on first use (tests and
# scripts that never need it never open it), and recreated if DATABASE_URL changes.
# DB_POOL=0 turns it off and goes back to one connection per request.

_pool = None
_pool_url = None
_pool_lock = threading.Lock()


def pooling_enabled() -> bool:
    return os.environ.get("DB_POOL", "1") != "0"


def _get_pool():
    global _pool, _pool_url
    url = database_url()
    with _pool_lock:
        if _pool is None or _pool_url != url:
            from psycopg_pool import ConnectionPool

            if _pool is not None:
                _pool.close()
            _pool = ConnectionPool(
                url,
                kwargs=CONNECT_OPTIONS,
                min_size=int(os.environ.get("DB_POOL_MIN", "1")),
                # Supabase's free session pooler allows a few client connections: stay well below.
                max_size=int(os.environ.get("DB_POOL_MAX", "5")),
                max_idle=300,  # close connections unused for 5 minutes
                timeout=15,  # wait at most this long for a free connection
                check=ConnectionPool.check_connection,  # a connection dropped by the server is replaced
                open=True,
                name="api",
            )
            _pool_url = url
        return _pool


def close_pool() -> None:
    """Close every pooled connection (on shutdown)."""
    global _pool, _pool_url
    with _pool_lock:
        if _pool is not None:
            _pool.close()
        _pool, _pool_url = None, None


def _borrow():
    """A connection and the function that gives it back when the request is over."""
    if pooling_enabled():
        pool = _get_pool()
        connection = pool.getconn()
        return connection, lambda: pool.putconn(connection)
    connection = get_connection()
    return connection, connection.close


def database_connection():
    """FastAPI dependency: one connection per request, shared by every repository.

    The transaction is committed when the request succeeds and rolled back if it raises.
    """
    connection, release = _borrow()
    try:
        yield connection
    except BaseException:
        connection.rollback()
        release()
        raise
    try:
        connection.commit()
    finally:
        release()


class LazyConnection:
    """Opens (or borrows) the real connection only on the first query.

    Routes that answer from the cache never touch PostgreSQL, so they should not pay for a
    connection either. `factory` returns a connection, or a (connection, release) pair.
    """

    def __init__(self, factory=None):
        self._factory = factory or _borrow
        self._connection = None
        self._release = None

    @property
    def opened(self) -> bool:
        return self._connection is not None

    def execute(self, *args, **kwargs):
        if self._connection is None:
            made = self._factory()
            if isinstance(made, tuple):
                self._connection, self._release = made
            else:
                self._connection, self._release = made, made.close
        return self._connection.execute(*args, **kwargs)

    def finish(self, failed: bool) -> None:
        if self._connection is None:
            return
        try:
            if failed:
                self._connection.rollback()
            else:
                self._connection.commit()
        finally:
            self._release()
            self._connection = None
            self._release = None


def lazy_database_connection():
    """FastAPI dependency like database_connection, but the connection opens on first use."""
    connection = LazyConnection()
    try:
        yield connection
    except BaseException:
        connection.finish(failed=True)
        raise
    connection.finish(failed=False)
