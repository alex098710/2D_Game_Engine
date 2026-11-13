import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.admin.router import router as admin_router
from app.ai_learning.router import router as ai_router
from app.auth.router import router as auth_router
from app.body_limit import BodyLimitMiddleware
from app.catalog.router import router as catalog_router
from app.config import check_configuration, is_production
from app.database import close_pool, database_connection
from app.play.router import router as play_router
from app.profile.router import router as profile_router
from app.projects.router import router as projects_router
from app.rate_limit import RateLimitMiddleware, SlidingWindowLimiter, proxy_settings
from app.request_context import RequestContextMiddleware
from app.security_headers import SecurityHeadersMiddleware
from app.settings.router import router as settings_router

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Refuses to start in production with weak secrets or insecure origins.
    check_configuration()
    if is_production():
        # Deploys apply pending migrations by themselves (each runs only once).
        from app.database import get_connection
        from app.migrate import apply_pending
        with get_connection() as connection:
            applied = apply_pending(connection)
        logging.getLogger("app").info("%d migration(s) applied at start-up", len(applied))
    yield
    close_pool()  # give the pooled database connections back on shutdown


app = FastAPI(
    title="2D Engine",
    version="2.1.0",
    lifespan=lifespan,
    # The interactive docs describe every route; do not publish them in production.
    docs_url=None if is_production() else "/docs",
    redoc_url=None,
    openapi_url=None if is_production() else "/openapi.json",
)
# Middleware runs from the last added (outermost) to the first added.
app.add_middleware(SecurityHeadersMiddleware)
app.state.rate_limiter = SlidingWindowLimiter()
_hops, _edge = proxy_settings()
app.add_middleware(
    RateLimitMiddleware,
    limiter=app.state.rate_limiter,
    trusted_proxy_hops=_hops,
    trust_edge_header=_edge,
    multiplier=int(os.environ.get("RATE_LIMIT_MULTIPLIER", "1")),
)
app.add_middleware(BodyLimitMiddleware)
app.add_middleware(RequestContextMiddleware)
# CORS is outermost so every answer carries its headers, also 429, 413 and 500:
# without them the browser hides the real error behind a network failure.
# Origins allowed to call this API from a browser (comma separated).
_origins = os.environ.get("FRONTEND_ORIGINS", "http://localhost:5173")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _origins.split(",") if o.strip() and o.strip() != "*"],
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    expose_headers=["X-Request-ID", "Retry-After", "X-Attempts-Remaining"],
    max_age=600,
)



@app.exception_handler(RequestValidationError)
async def validation_error(_request: Request, error: RequestValidationError):
    """422 with where and why, never the value that was sent: it may be a password or a token."""
    errors = error.errors()
    # A body that may come sealed is "SealedIn | LoginIn": pydantic reports both branches.
    # Keep the errors of the plain branch, and drop the model names from the location.
    plain = [e for e in errors if "SealedIn" not in e.get("loc", ())] or errors
    detail = [
        {"type": e.get("type"), "loc": [part for part in e.get("loc", ()) if not _is_model_name(part)], "msg": e.get("msg")}
        for e in plain
    ]
    return JSONResponse(status_code=422, content={"detail": detail})


def _is_model_name(part) -> bool:
    return isinstance(part, str) and part[:1].isupper() and part.endswith("In")


app.include_router(auth_router)
app.include_router(projects_router)
app.include_router(ai_router)
app.include_router(play_router)
app.include_router(settings_router)
app.include_router(catalog_router)
app.include_router(profile_router)
app.include_router(admin_router)


# Uptime monitors (UptimeRobot) check with HEAD: answer it like GET, without the body.
@app.api_route("/health", methods=["GET", "HEAD"])
def health():
    return {"ok": True}


@app.api_route("/health/db", methods=["GET", "HEAD"])
def health_database(connection=Depends(database_connection)):
    """Check that the database answers (the uptime monitor calls it). Says nothing else."""
    connection.execute("select 1").fetchone()
    return {"ok": True}
