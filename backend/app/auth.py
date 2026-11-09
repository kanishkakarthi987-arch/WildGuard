"""Authentication: per-device API keys for ingestion, one admin token for management.

Keys are stored only as SHA-256 hashes (they are long random strings, so a fast hash is
appropriate). A key is shown once, when the device is provisioned.
"""

import hashlib
import hmac
import secrets

from importlib import import_module

try:
    _fastapi = import_module("fastapi")
    Header = _fastapi.Header
    HTTPException = _fastapi.HTTPException
    Query = _fastapi.Query
except ModuleNotFoundError:
    # Keep key utilities usable in environments where the API dependency is absent.
    def Header(default=""):
        return default

    def Query(default=None):
        return default

    class HTTPException(Exception):
        def __init__(self, status_code: int, detail: str):
            self.status_code = status_code
            self.detail = detail
            super().__init__(detail)

from . import config, db


def generate_key() -> str:
    return "wg_" + secrets.token_urlsafe(24)


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def _admin_ok(token: str) -> bool:
    return bool(token) and hmac.compare_digest(token.encode(), config.ADMIN_TOKEN.encode())


def require_admin(x_admin_token: str = Header(default="")) -> None:
    if not _admin_ok(x_admin_token):
        raise HTTPException(status_code=401, detail="Admin token required (X-Admin-Token header)")


def device_auth(kind: str):
    """FastAPI dependency: authenticate a device of the given kind.

    Devices send X-API-Key. For dashboard uploads and simulators, the admin token plus a
    ?device_id= query parameter is accepted instead, so no real device key is needed.
    """

    def dependency(
        x_api_key: str = Header(default=""),
        x_admin_token: str = Header(default=""),
        device_id: str | None = Query(default=None),
    ) -> dict:
        if x_api_key:
            device = db.get_device_by_key_hash(hash_key(x_api_key))
            if device is None:
                raise HTTPException(status_code=401, detail="Invalid API key")
        elif _admin_ok(x_admin_token):
            if not device_id:
                raise HTTPException(status_code=400, detail="device_id query parameter required with the admin token")
            device = db.get_device(device_id)
            if device is None:
                raise HTTPException(status_code=404, detail=f"Unknown device {device_id}")
        else:
            raise HTTPException(status_code=401, detail="X-API-Key header required")
        if device["kind"] != kind:
            raise HTTPException(
                status_code=403, detail=f"{device['id']} is a {device['kind']} device, not a {kind}"
            )
        return device

    return dependency
