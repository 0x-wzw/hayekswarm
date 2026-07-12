from __future__ import annotations
import os
from fastapi import Request, HTTPException, Depends
from fastapi.security import APIKeyHeader
from voidtether.core.auth import HMACVerifier

# Verifier is resolved lazily so VOIDTETHER_HMAC_SECRET can be configured at runtime
# (there is no public default secret — see voidtether.core.auth). When the env var is
# unset, HMACVerifier uses a fail-closed ephemeral secret and all signatures are rejected.
_verifier: HMACVerifier | None = None
_verifier_secret: str | None = None


def _get_verifier() -> HMACVerifier:
    global _verifier, _verifier_secret
    secret = os.environ.get("VOIDTETHER_HMAC_SECRET")
    if _verifier is None or secret != _verifier_secret:
        _verifier = HMACVerifier(secret=secret)
        _verifier_secret = secret
    return _verifier

# Headers for authentication
X_TETHER_SIGNATURE = APIKeyHeader(name="X-Tether-Signature")
X_TETHER_TIMESTAMP = APIKeyHeader(name="X-Tether-Timestamp")

async def verify_tether_auth(
    request: Request, 
    signature: str = Depends(X_TETHER_SIGNATURE), 
    timestamp: int = Depends(X_TETHER_TIMESTAMP)
):
    """
    Dependency to verify HMAC signatures on requests.
    Expects the request body as the data to verify.
    """
    body = await request.body()
    data = body.decode("utf-8")
    
    if not _get_verifier().verify(data, signature, timestamp):
        raise HTTPException(
            status_code=401, 
            detail="Invalid or expired Tether signature. Access denied."
        )
    return True
