"""Basic VoidTether mesh example — registering and discovering agents."""

import asyncio
from voidtether import Mesh, TetherManifest, Protocol


async def main():
    # Create the mesh
    mesh = Mesh()
    
    # Register a Hermes agent
    hermes_agent = TetherManifest(
        tether_id="vt-hermes-researcher",
        name="Hermes Research Agent",
        origin_protocol=Protocol.HERMES,
        capabilities={
            "tasks": ["research", "web_search", "summarize"],
            "modalities": ["text", "structured_output"],
            "streaming": True,
        },
    )
    mesh.register(hermes_agent)
    
    # Register an A2A agent
    a2a_agent = TetherManifest(
        tether_id="vt-a2a-coder",
        name="A2A Code Agent",
        origin_protocol=Protocol.A2A,
        capabilities={
            "tasks": ["code_generation", "code_review", "debugging"],
            "modalities": ["text", "structured_output"],
        },
    )
    mesh.register(a2a_agent)
    
    # Register an MCP server
    mcp_server = TetherManifest(
        tether_id="vt-mcp-filesystem",
        name="MCP Filesystem Server",
        origin_protocol=Protocol.MCP,
        capabilities={
            "tasks": ["read_file", "write_file", "search_files"],
            "modalities": ["text"],
        },
    )
    mesh.register(mcp_server)
    
    # Register an OpenClaw agent
    openclaw_agent = TetherManifest(
        tether_id="vt-openclaw-video",
        name="OpenClaw Video Agent",
        origin_protocol=Protocol.OPENCLAW,
        capabilities={
            "tasks": ["video_render", "animation", "compose"],
            "modalities": ["text", "video", "html"],
            "streaming": True,
        },
    )
    mesh.register(openclaw_agent)
    
    # List all agents
    print("⚫ Tethered Agents:")
    for agent in mesh.list_agents():
        print(f"   {agent.tether_id:30} [{agent.origin_protocol.value:10}] {agent.tasks}")
    
    # Discover agents for specific tasks
    print("\n⚫ Discovery:")
    for task in ["code_review", "research", "video_render", "read_file"]:
        agent = mesh.discover(task)
        if agent:
            print(f"   {task:20} -> {agent.tether_id} ({agent.origin_protocol.value})")
        else:
            print(f"   {task:20} -> NO AGENT FOUND")
    
    # Cross-protocol delegation (Hermes asking an A2A agent to review code)
    print("\n⚫ Cross-Protocol Delegation:")
    result = await mesh.auto_delegate(
        task="code_review",
        input_data={"code": "def hello(): print('world')"},
        source="vt-hermes-researcher",
        source_protocol=Protocol.HERMES,
    )
    print(f"   Result: {result}")


if __name__ == "__main__":
    asyncio.run(main())
