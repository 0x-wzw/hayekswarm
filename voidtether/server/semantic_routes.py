from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from voidtether.server.sessions import SessionManager
from voidtether.core.semantic_registry import registry

router = APIRouter()

@router.get("/api/sessions/{session_id}/related")
async def get_related_sessions(session_id: str):
    """Find other sessions that are semantically linked to this one."""
    related = registry.get_related_sessions(session_id)
    return {
        "session_id": session_id,
        "related": related,
        "entities": list(registry.get_entities_for_session(session_id))
    }
