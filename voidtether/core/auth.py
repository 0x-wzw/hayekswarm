"""Tether Auth — HMAC-based verification for inter-agent messages."""

from __future__ import annotations
import hashlib
import hmac
import os
import time
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Sensible default for local dev ONLY. Production MUST set VOIDTETHER_HMAC_SECRET.
_DEFAULT_DEV_SECRET = "voidtether-dev-insecure-secret"


class HMACVerifier:
    """HMAC-SHA256 verifier for TetherEnvelope authentication.
    
    Provides sign/verify for inter-agent messages using shared secrets.
    
    The secret is resolved in order:
    1. ``secret`` constructor argument
    2. ``VOIDTETHER_HMAC_SECRET`` environment variable
    3. Dev fallback (emits a warning — never use in production)
    """
    
    def __init__(self, secret: str | None = None):
        resolved = secret or os.environ.get("VOIDTETHER_HMAC_SECRET") or _DEFAULT_DEV_SECRET
        if resolved == _DEFAULT_DEV_SECRET:
            logger.warning(
                "HMACVerifier using insecure default secret. "
                "Set VOIDTETHER_HMAC_SECRET env var for production."
            )
        self._secret = resolved.encode("utf-8")
    
    def sign(self, data: str, timestamp: int | None = None) -> str:
        """Sign data with HMAC-SHA256. Returns hex digest."""
        if timestamp is None:
            timestamp = int(time.time())
        message = f"{timestamp}:{data}".encode("utf-8")
        return hmac.new(self._secret, message, hashlib.sha256).hexdigest()
    
    def verify(self, data: str, signature: str, timestamp: Any, max_drift: int = 300) -> bool:
        """Verify an HMAC signature. Checks both hash and timestamp freshness."""
        try:
            ts_int = int(timestamp)
        except (ValueError, TypeError):
            return False

        # Check timestamp freshness
        now = int(time.time())
        if abs(now - ts_int) > max_drift:
            return False

        # Check HMAC
        message = f"{ts_int}:{data}".encode("utf-8")
        expected = hmac.new(self._secret, message, hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature, expected)
