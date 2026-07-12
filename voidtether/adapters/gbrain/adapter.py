"""GBrain Protocol Adapter — bridges Garry Tan's GBrain knowledge compounder."""

from __future__ import annotations
from typing import Any
from voidtether.core.bridge import BaseAdapter
from voidtether.core.manifest import TetherManifest, Protocol, ProtocolEndpoint


# GBrain's 25 core skills mapped to VoidTether capability tasks
GBRAIN_SKILL_MAP = {
    # Always-on
    "signal-detector": "ambient_signal_capture",
    "brain-ops": "brain_read_enrich_write",
    # Content ingestion
    "ingest": "content_ingestion",
    "idea-ingest": "idea_ingestion",
    "media-ingest": "media_ingestion",
    "meeting-ingestion": "meeting_ingestion",
    # Brain operations
    "enrich": "entity_enrichment",
    "query": "hybrid_search_query",
    "search": "keyword_search",
    "maintain": "brain_maintenance",
    "citation-fixer": "citation_repair",
    "repo-architecture": "filing_rules",
    "publish": "publish_brain_pages",
    "data-research": "structured_research",
    # Operational
    "daily-task-manager": "task_management",
    "daily-task-prep": "morning_prep",
    "cron-scheduler": "cron_scheduling",
    "reports": "timestamped_reports",
    "cross-modal-review": "quality_gate_review",
    "webhook-transforms": "webhook_ingestion",
    "testing": "skill_validation",
    "skill-creator": "skill_creation",
    # Identity
    "soul-audit": "identity_interview",
    "briefing": "daily_briefing",
}


class GBrainAdapter(BaseAdapter):
    """GBrain protocol adapter — translates GBrain MCP-style tools to TetherManifest.
    
    GBrain is a skill pack that exposes 25+ MCP tools for knowledge management:
    hybrid RAG search, entity enrichment, content ingestion, meeting processing,
    daily briefings, and more.

    This adapter bridges GBrain's MCP server into the VoidTether mesh, making
    its 25 skills discoverable and callable by ANY protocol — not just Hermes
    or OpenClaw agents.

    Key mappings:
      GBrain Skill      -> Tether capability (task)
      GBrain MCP Server -> TetherManifest with 25 capabilities
      GBrain query      -> Tether task delegation (search/query)
    """

    protocol: Protocol = Protocol.GBRAIN

    def __init__(self):
        super().__init__()

    def normalize_output(self, data: dict[str, Any]) -> dict[str, Any]:
        """Convert GBrain MCP tool output to VoidTether format.
        
        GBrain queries return structured search results with citations,
        compiled truth sections, and timeline entries.
        """
        # GBrain query results have a specific structure
        if "results" in data:
            results = data["results"]
            return {
                "text": "\n\n".join(r.get("compiled_truth", r.get("content", "")) for r in results),
                "results": results,
                "source": "gbrain",
                "metadata": {
                    "total_results": len(results),
                    "search_type": data.get("search_type", "hybrid"),
                    "citations": [r.get("citation") for r in results if r.get("citation")],
                },
            }
        
        # Enrich results
        if "enriched" in data:
            return {
                "text": data.get("summary", ""),
                "enriched_pages": data.get("enriched", []),
                "source": "gbrain",
                "metadata": {"enrichment_tier": data.get("tier", "unknown")},
            }
        
        # Ingest results
        if "slug" in data:
            return {
                "text": data.get("summary", f"Page '{data['slug']}' ingested"),
                "slug": data.get("slug"),
                "source": "gbrain",
                "metadata": {"type": data.get("type", "page")},
            }
        
        # Fallback: pass through
        return {"text": str(data), "source": "gbrain"}
    
    def denormalize_input(self, data: dict[str, Any]) -> dict[str, Any]:
        """Convert VoidTether format to GBrain MCP tool call.
        
        Routes to the appropriate GBrain skill based on the task type.
        """
        task_type = data.get("task_type", data.get("skill", "query"))
        
        # Map VoidTether task names back to GBrain skill names
        reverse_map = {v: k for k, v in GBRAIN_SKILL_MAP.items()}
        gbrain_skill = reverse_map.get(task_type, task_type)
        
        # Build MCP-compatible tool call
        if gbrain_skill in ("query", "hybrid_search_query"):
            return {
                "method": "tools/call",
                "params": {
                    "name": "gbrain_query",
                    "arguments": {
                        "question": data.get("input", {}).get("question", ""),
                    },
                },
            }
        
        elif gbrain_skill in ("search", "keyword_search"):
            return {
                "method": "tools/call",
                "params": {
                    "name": "gbrain_search",
                    "arguments": {
                        "query": data.get("input", {}).get("query", ""),
                    },
                },
            }
        
        elif gbrain_skill in ("enrich", "entity_enrichment"):
            return {
                "method": "tools/call",
                "params": {
                    "name": "gbrain_enrich",
                    "arguments": {
                        "slug": data.get("input", {}).get("slug", ""),
                        "tier": data.get("input", {}).get("tier", 2),
                    },
                },
            }
        
        elif gbrain_skill in ("ingest", "idea-ingest", "media-ingest", "meeting-ingestion",
                              "content_ingestion", "idea_ingestion", "media_ingestion", "meeting_ingestion"):
            return {
                "method": "tools/call",
                "params": {
                    "name": "gbrain_ingest",
                    "arguments": {
                        "input": data.get("input", {}).get("content", data.get("input", "")),
                        "type": gbrain_skill,
                    },
                },
            }
        
        elif gbrain_skill in ("briefing", "daily_briefing"):
            return {
                "method": "tools/call",
                "params": {
                    "name": "gbrain_briefing",
                    "arguments": data.get("input", {}),
                },
            }
        
        # Generic fallback
        return {
            "method": "tools/call",
            "params": {
                "name": f"gbrain_{gbrain_skill.replace('-', '_')}",
                "arguments": data.get("input", {}),
            },
        }
    
    async def execute(self, manifest: TetherManifest, task_type: str, input_data: dict[str, Any]) -> dict[str, Any]:
        """Execute a task via GBrain's MCP server."""
        gbrain_endpoint = None
        for p in manifest.protocols:
            if p.protocol == Protocol.GBRAIN:
                gbrain_endpoint = p.endpoint_url
                break
            elif p.protocol == Protocol.MCP:
                gbrain_endpoint = p.endpoint_url
                break
        
        if not gbrain_endpoint:
            return {"error": "No GBrain MCP endpoint found in manifest"}
        
        # TODO: Implement actual MCP client transport (stdio/SSE)
        # For v0.3.0, this is a protocol-compliant placeholder
        return {
            "status": "completed",
            "results": [],
            "source": "gbrain",
            "note": "GBrain adapter placeholder — implement MCP HTTP transport",
        }


def gbrain_skills_to_manifest(
    name: str = "GBrain",
    skills: list[str] | None = None,
    mcp_url: str = "http://localhost:8787/mcp",
) -> TetherManifest:
    """Create a TetherManifest from GBrain's skill list.
    
    Args:
        name: Display name for this GBrain instance
        skills: List of GBrain skill names to expose (defaults to all)
        mcp_url: URL of the GBrain MCP server
    
    Returns:
        TetherManifest ready for mesh registration
    """
    if skills is None:
        skills = list(GBRAIN_SKILL_MAP.keys())
    
    # Map GBrain skill names to VoidTether capability tasks
    capability_tasks = []
    for skill in skills:
        if skill in GBRAIN_SKILL_MAP:
            capability_tasks.append(GBRAIN_SKILL_MAP[skill])
        else:
            # Unknown skill — pass through as-is
            capability_tasks.append(skill)
    
    return TetherManifest(
        tether_id=f"vt-gbrain-{name.lower().replace(' ', '-')}",
        name=name,
        origin_protocol=Protocol.GBRAIN,
        capabilities={
            "tasks": capability_tasks,
            "modalities": ["text", "structured_output", "citations"],
            "streaming": False,
            "knowledge_provider": True,  # Flag: this is a knowledge source, not just a compute agent
            "gbrain_skills": skills,      # Original skill names for reference
        },
        protocols=[
            ProtocolEndpoint(
                protocol=Protocol.GBRAIN,
                endpoint_url=mcp_url,
                tools=[f"gbrain_{s.replace('-', '_')}" for s in skills],
                config={"framework": "gbrain", "version": "0.10.0"},
            ),
        ],
        metadata={
            "framework": "gbrain",
            "gbrain_version": "0.10.0",
            "description": "GBrain personal knowledge compounder — hybrid RAG search, entity enrichment, content ingestion",
            "author": "Garry Tan",
            "repo": "https://github.com/garrytan/gbrain",
            "philosophy": "Thin Harness, Fat Skills — intelligence lives in skill files, not the runtime",
        },
    )