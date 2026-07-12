"""HayekSwarm Marketplace — API key authentication."""

from __future__ import annotations

import secrets
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader

from server.database import Database

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)

_db_for_auth: Database | None = None


def set_auth_db(db: Database):
    global _db_for_auth
    _db_for_auth = db


def generate_api_key() -> str:
    """Generate a cryptographically secure API key."""
    return "hsk_" + secrets.token_hex(32)


async def verify_api_key(
    api_key: str = Security(API_KEY_HEADER),
) -> dict:
    """Verify an API key and return the key record.

    Raises 401 if the key is missing, invalid, or inactive.
    """
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-API-Key header",
        )
    db = _db_for_auth
    if db is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Auth database not initialized",
        )
    record = db.get_api_key(api_key)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or inactive API key",
        )
    db.touch_api_key(record["id"])
    return record
