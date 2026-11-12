
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, ValidationError

from app.rate_limit import client_ip, proxy_settings

from .auth_service import LOCKOUT_WINDOW, AuthService
from .dependencies import bearer_token, current_user, get_auth_service, get_commit
from .errors import EmailAlreadyRegisteredError, InvalidCredentialsError, InvalidTokenError, TooManyAttemptsError
from .password_policy import WeakPasswordError
from .sealed import SealedError, new_challenge, open_sealed, seal_answer
from .user import User

router = APIRouter(prefix="/auth", tags=["auth"])

_EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class RegisterIn(BaseModel):
    # 3-20 letters, digits or underscores: easy to read, to type and to mention.
    username: str = Field(min_length=3, max_length=20, pattern=r"^[A-Za-z0-9_]+$")
    email: str = Field(pattern=_EMAIL_PATTERN, max_length=254)
    password: str = Field(min_length=8, max_length=128)


class LoginIn(BaseModel):
    email: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class RefreshIn(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=200)


class PasswordChangeIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class LogoutIn(BaseModel):
    refresh_token: str | None = Field(default=None, max_length=200)


class SealedIn(BaseModel):
    """Any of the bodies above, encrypted as one block (see sealed.py)."""

    sealed: str = Field(min_length=10, max_length=4096)


def _open(body, model):
    """(the plain body, the key to seal the answer with, or None for a plain request)."""
    if not isinstance(body, SealedIn):
        return body, None
    try:
        data, key = open_sealed(body.sealed)
    except SealedError:
        raise HTTPException(status_code=400, detail="Sealed request invalid or expired")
    try:
        return model(**data), key
    except ValidationError as error:
        # Never echo the input back: it may hold a password.
        detail = [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in error.errors()]
        raise HTTPException(status_code=422, detail=detail)


def _answer(data, key):
    return data if key is None else seal_answer(data, key)


@router.get("/challenge")
def challenge(response: Response):
    """A one-time id and the public key to seal one account request with."""
    response.headers["Cache-Control"] = "no-store"
    return new_challenge()


def _user_json(user: User) -> dict:
    # Never include the salt or the password hash.
    return {"id": user.id, "username": user.username, "email": user.email}


def _client_ip(request: Request) -> str:
    """The caller's real address, read the same way as the rate limiter.

    Behind Render's proxy request.client is the proxy itself: counting failed
    logins by it would lock everybody out after 20 mistakes by anyone.
    """
    hops, edge = proxy_settings()
    ip = client_ip(request.scope, hops, edge)
    return "" if ip == "unknown" else ip


@router.post("/register", status_code=201)
def register(body: SealedIn | RegisterIn, service: AuthService = Depends(get_auth_service)):
    body, key = _open(body, RegisterIn)
    try:
        user = service.register(body.username, body.email, body.password)
    except EmailAlreadyRegisteredError:
        raise HTTPException(status_code=409, detail="Email already registered")
    except WeakPasswordError as error:
        raise HTTPException(status_code=422, detail=str(error))
    return _answer(_user_json(user), key)


@router.post("/login")
def log_in(body: SealedIn | LoginIn, request: Request, service: AuthService = Depends(get_auth_service),
           commit=Depends(get_commit)):
    body, key = _open(body, LoginIn)
    try:
        pair = service.log_in(body.email, body.password, _client_ip(request), request.headers.get("user-agent", ""))
    except TooManyAttemptsError:
        # The lockout lasts the window of failed attempts; say so, like the rate limiter does.
        raise HTTPException(status_code=429, detail="Too many failed attempts, try again later",
                            headers={"Retry-After": str(int(LOCKOUT_WINDOW.total_seconds()))})
    except InvalidCredentialsError as error:
        commit()  # keep the failed attempt, or the lockout could never count it
        headers = {} if error.attempts_left is None else {"X-Attempts-Remaining": str(error.attempts_left)}
        raise HTTPException(status_code=401, detail="Invalid email or password", headers=headers)
    return _answer(pair.to_json(), key)


@router.post("/refresh")
def refresh(body: SealedIn | RefreshIn, request: Request, service: AuthService = Depends(get_auth_service),
            commit=Depends(get_commit)):
    body, key = _open(body, RefreshIn)
    try:
        pair = service.refresh(body.refresh_token, request.headers.get("user-agent", ""))
    except InvalidTokenError:
        commit()  # keep a family revocation caused by a reused token
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    return _answer(pair.to_json(), key)


@router.get("/me")
def me(user: User = Depends(current_user)):
    return _user_json(user)


@router.post("/logout", status_code=204)
def log_out(body: LogoutIn | None = None, token: str = Depends(bearer_token),
            service: AuthService = Depends(get_auth_service)):
    service.log_out(token, body.refresh_token if body else None)
    return Response(status_code=204)


@router.post("/logout-all", status_code=204)
def log_out_everywhere(user: User = Depends(current_user), service: AuthService = Depends(get_auth_service)):
    service.log_out_everywhere(user.id)
    return Response(status_code=204)


@router.post("/password", status_code=204)
def change_password(body: SealedIn | PasswordChangeIn, user: User = Depends(current_user),
                    service: AuthService = Depends(get_auth_service)):
    """Change the password. Every refresh token of the account is revoked, so other
    devices are logged out; the current access token keeps working until it expires."""
    body, _ = _open(body, PasswordChangeIn)
    try:
        service.change_password(user, body.current_password, body.new_password)
    except InvalidCredentialsError:
        raise HTTPException(status_code=400, detail="Current password is wrong")
    except WeakPasswordError as error:
        raise HTTPException(status_code=422, detail=str(error))
    return Response(status_code=204)
