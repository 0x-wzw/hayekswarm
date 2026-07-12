"""Tether Auth — HMAC-based verification for inter-agent messages."""

from __future__ import annotations
import hashlib
import hmac
import os
import time
import logging
import secrets
from typing import Any

logger = logging.getLogger(__name__)


class HMACVerifier:
    """HMAC-SHA256 verifier for TetherEnvelope authentication.

    Provides sign/verify for inter-agent messages using shared secrets.

    The secret is resolved in order:
    1. ``secret`` constructor argument
    2. ``VOIDTETHER_HMAC_SECRET`` environment variable
    3. If neither is set, an EPHEMERAL random per-process secret is generated
       (fail-closed): signatures from other processes/nodes will not verify
       until a shared ``VOIDTETHER_HMAC_SECRET`` is configured. There is
       deliberately no shared hardcoded default — a public constant would make
       every signature forgeable.
    """

    def __init__(self, secret: str | None = None):
        resolved = secret or os.environ.get("VOIDTETHER_HMAC_SECRET")
        if not resolved:
            resolved = secrets.token_hex(32)
            logger.warning(
                "HMACVerifier: no secret provided and VOIDTETHER_HMAC_SECRET is unset; "
                "generated an ephemeral per-process secret. Inter-agent/cross-process "
                "authentication will FAIL until VOIDTETHER_HMAC_SECRET is set to a shared value."
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
