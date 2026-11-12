"""Sealed requests: account data travels as one encrypted block, inside HTTPS.

HTTPS already protects the data on the way. Sealing also keeps it out of the browser's own
tools: the network tab, exported HAR files and extensions that read requests see an opaque
block instead of the email, the password or the session tokens.

How it works (the same hybrid scheme TLS uses):

1. The browser asks GET /auth/challenge: a one-time id and the server's RSA public key.
2. It makes a random AES-256-GCM key, encrypts the JSON body with it (the challenge id is the
   associated data, so the block is tied to that id) and wraps the AES key with RSA-OAEP-SHA256.
3. It sends {"sealed": "v1.<id>.<wrapped key>.<iv>.<ciphertext>"} (base64url parts).
4. The server unwraps the key, decrypts, and burns the id: a copied block cannot be sent again,
   and an id older than CHALLENGE_TTL is refused.
5. The answer (the tokens) is encrypted with the same AES key, which only that page knows.

The RSA key pair lives in memory and is created when the API starts; a restart only means the
browser asks for a new challenge. Nothing here replaces HTTPS or the password hashing.
"""
import base64
import json
import os
import secrets
import threading

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.structures.lru_cache import LRUCache

VERSION = "v1"
CHALLENGE_TTL = 120  # seconds a challenge stays valid
RESPONSE_AAD = b"pixelforge-response"
MAX_SEALED_LENGTH = 4096

_key = None
_public_spki = None
_key_lock = threading.Lock()
_burn_lock = threading.Lock()
# Challenges handed out and not used yet. Bounded: an attacker asking for many only pushes the
# oldest out (those requests then fail and the browser asks again).
_challenges = LRUCache(capacity=20000, ttl_seconds=CHALLENGE_TTL)


class SealedError(Exception):
    """The block is malformed, was already used, expired, or does not decrypt."""


def _keys():
    global _key, _public_spki
    with _key_lock:
        if _key is None:
            _key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            _public_spki = _key.public_key().public_bytes(
                serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
            )
        return _key, _public_spki


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def new_challenge() -> dict:
    """A one-time id and the public key to seal one request with."""
    _, spki = _keys()
    challenge_id = secrets.token_urlsafe(18)
    _challenges.put(challenge_id, True)
    return {"id": challenge_id, "key": _b64e(spki), "alg": "RSA-OAEP-256+A256GCM", "expires_in": CHALLENGE_TTL}


def open_sealed(sealed: str) -> tuple:
    """(the decrypted JSON object, the AES key to seal the answer with). Burns the challenge."""
    if not isinstance(sealed, str) or len(sealed) > MAX_SEALED_LENGTH:
        raise SealedError("bad block")
    parts = sealed.split(".")
    if len(parts) != 5 or parts[0] != VERSION:
        raise SealedError("bad block")
    _, challenge_id, wrapped, iv, ciphertext = parts
    # Single use: whatever happens next, this id cannot be used again. get() treats an expired
    # entry as absent; the lock makes "check and burn" one step, so two copies cannot both pass.
    with _burn_lock:
        known = _challenges.get(challenge_id) is not None
        _challenges.delete(challenge_id)
    if not known:
        raise SealedError("unknown or expired challenge")
    key, _ = _keys()
    try:
        aes_key = key.decrypt(
            _b64d(wrapped),
            padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None),
        )
        if len(aes_key) != 32:
            raise SealedError("bad key")
        plain = AESGCM(aes_key).decrypt(_b64d(iv), _b64d(ciphertext), challenge_id.encode())
        data = json.loads(plain)
    except SealedError:
        raise
    except Exception as error:  # wrong key, tampered block, invalid JSON: all the same to the caller
        raise SealedError("cannot open") from error
    if not isinstance(data, dict):
        raise SealedError("not an object")
    return data, aes_key


def seal_answer(data, aes_key: bytes) -> dict:
    """Encrypt an answer with the key the browser sent, so only that page can read it."""
    iv = os.urandom(12)
    plain = json.dumps(data, separators=(",", ":")).encode()
    ciphertext = AESGCM(aes_key).encrypt(iv, plain, RESPONSE_AAD)
    return {"sealed": f"{_b64e(iv)}.{_b64e(ciphertext)}"}


def seal_for_tests(data: dict, challenge: dict) -> tuple:
    """Seal a body like the browser does (used by the tests). Returns (sealed, aes_key)."""
    public_key = serialization.load_der_public_key(_b64d(challenge["key"]))
    aes_key = AESGCM.generate_key(bit_length=256)
    iv = os.urandom(12)
    ciphertext = AESGCM(aes_key).encrypt(iv, json.dumps(data).encode(), challenge["id"].encode())
    wrapped = public_key.encrypt(
        aes_key, padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None)
    )
    return f"{VERSION}.{challenge['id']}.{_b64e(wrapped)}.{_b64e(iv)}.{_b64e(ciphertext)}", aes_key


def open_answer_for_tests(answer: dict, aes_key: bytes):
    iv, ciphertext = answer["sealed"].split(".")
    return json.loads(AESGCM(aes_key).decrypt(_b64d(iv), _b64d(ciphertext), RESPONSE_AAD))
