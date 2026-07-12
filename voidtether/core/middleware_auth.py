from __future__ import annotations
import os
from fastapi import Request, HTTPException, Depends
from fastapi.security import APIKeyHeader
from voidtether.core.auth import HMACVerifier

# Secret is resolved from env or default
HMAC_SECRET = os.environ.get("VOIDTETHER_HMAC_SECRET", "voidtether-dev-insecure-secret")
verifier = HMACVerifier(secret=HMAC_SECRET)

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
    
    if not verifier.verify(data, signature, timestamp):
        raise HTTPException(
            status_code=401, 
            detail="Invalid or expired Tether signature. Access denied."
        )
    return True
