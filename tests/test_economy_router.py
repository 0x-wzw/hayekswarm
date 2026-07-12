"""Tests for the EoM EconomicRouter — auction-based economic routing."""

from __future__ import annotations
import asyncio
import pytest

from voidtether.core.manifest import TetherManifest, Protocol, ProtocolEndpoint
from voidtether.core.router import TetherTask
from voidtether.economy import (
    EconomicRouter,
    EconomicEngine,
    EconomyConfig,
    EngineConfig,
    RewardConfig,
    EvolutionConfig,
    EconomicAgent,
    Auctioneer,
    EconomicPopulation,
    AgentStatus,
)
from voidtether.mesh import Mesh


# ════════════════════════════════════════════════════════════════
# Fixtures
# ════════════════════════════════════════════════════════════════

@pytest.fixture
def economy_config():
    return EconomyConfig(
        engine=EngineConfig(
            initial_wealth=100.0,
            base_bid=1.0,
            novice_bid_epsilon=0.01,
            max_num_agents=100,
            min_num_agents=1,
            bid_scheme="fixed",
        ),
        reward=RewardConfig(
            reward_scheme="path_reward_only",
            path_reward_scale=10.0,
        ),
        evolution=EvolutionConfig(
            p_a=0.0,
            p_b=1.0,
        ),
    )


@pytest.fixture
def economic_router(economy_config):
    engine = EconomicEngine(config=economy_config)
    return EconomicRouter(engine)


@pytest.fixture
def sample_manifest():
    return TetherManifest(
        tether_id="test-agent-001",
        name="TestAgent",
        origin_protocol=Protocol.A2A,
        capabilities={"tasks": ["code_review", "summarize"], "modalities": ["text"]},
        protocols=[ProtocolEndpoint(protocol=Protocol.A2A, agent_card_url="http://localhost:8080/card")],
    )


@pytest.fixture
def hermes_manifest():
    return TetherManifest(
        tether_id="hermes-agent-001",
        name="HermesBot",
        origin_protocol=Protocol.HERMES,
        capabilities={"tasks": ["research", "write"], "skills": ["web-search"], "modalities": ["text"]},
        protocols=[ProtocolEndpoint(protocol=Protocol.HERMES, skill="web-search")],
    )


@pytest.fixture
def swarm_manifest():
    return TetherManifest(
        tether_id="swarm-agent-001",
        name="SwarmBot",
        origin_protocol=Protocol.SWARM,
        capabilities={"tasks": ["code_review", "research"], "modalities": ["text"]},
    )


# ════════════════════════════════════════════════════════════════
# Test EconomyConfig
# ════════════════════════════════════════════════════════════════

class TestEconomyConfig:
    def test_default_config(self):
        config = EconomyConfig()
        assert config.engine.initial_wealth == 0.5
        assert config.engine.base_bid == 0.1

    def test_config_engine_params(self, economy_config):
        assert economy_config.engine.initial_wealth == 100.0
        assert economy_config.engine.base_bid == 1.0


# ════════════════════════════════════════════════════════════════
# Test EconomicAgent
# ════════════════════════════════════════════════════════════════

class TestEconomicAgent:
    def test_agent_creation(self, sample_manifest):
        agent = EconomicAgent(sample_manifest, initial_wealth=100.0)
        assert agent.manifest.tether_id == "test-agent-001"
        assert agent.wealth == 100.0
        assert agent.get_status() == AgentStatus.NOVICE

    def test_gain_money(self, sample_manifest):
        agent = EconomicAgent(sample_manifest, initial_wealth=100.0)
        agent.gain_money(10.0)
        assert agent.wealth == 110.0

    def test_lose_money(self, sample_manifest):
        agent = EconomicAgent(sample_manifest, initial_wealth=100.0)
        agent.lose_money(10.0)
        assert agent.wealth == 90.0

    def test_bid_management(self, sample_manifest):
        agent = EconomicAgent(sample_manifest, initial_wealth=100.0)
        assert agent.get_bid() is None
        agent.set_bid(5.0)
        assert agent.get_bid() == 5.0

    def test_bankruptcy_check(self, sample_manifest):
        agent = EconomicAgent(sample_manifest, initial_wealth=100.0)
        assert agent.check_bankruptcy() is False
        agent.lose_money(200.0)
        assert agent.check_bankruptcy() is True

    def test_initialize(self, sample_manifest):
        agent = EconomicAgent(sample_manifest, initial_wealth=100.0)
        agent.lose_money(50.0)
        agent.initialize(initial_wealth=50.0)
        assert agent.wealth == 50.0
        assert agent.get_status() == AgentStatus.NOVICE

    def test_snapshot_restore(self, sample_manifest):
        agent = EconomicAgent(sample_manifest, initial_wealth=100.0)
        agent.set_bid(5.0)
        snap = agent.snapshot()
        assert snap["wealth"] == 100.0
        assert snap["bid"] == 5.0
        agent.lose_money(30.0)
        agent.restore(snap)
        assert agent.wealth == 100.0
        assert agent.get_bid() == 5.0


# ════════════════════════════════════════════════════════════════
# Test EconomicPopulation
# ════════════════════════════════════════════════════════════════

class TestEconomicPopulation:
    def test_add_and_get(self, sample_manifest, hermes_manifest):
        pop = EconomicPopulation()
        agent_a = EconomicAgent(sample_manifest, initial_wealth=100.0)
        agent_b = EconomicAgent(hermes_manifest, initial_wealth=100.0)
        pop.add_agent(agent_a)
        pop.add_agent(agent_b)
        assert len(pop) == 2
        assert pop.get_by_id(agent_a.id) is agent_a

    def test_remove(self, sample_manifest):
        pop = EconomicPopulation()
        agent = EconomicAgent(sample_manifest, initial_wealth=100.0)
        pop.add_agent(agent)
        pop.remove_agent(agent)
        assert len(pop) == 0

    def test_get_all(self, sample_manifest, hermes_manifest):
        pop = EconomicPopulation()
        pop.add_agent(EconomicAgent(sample_manifest, initial_wealth=100.0))
        pop.add_agent(EconomicAgent(hermes_manifest, initial_wealth=100.0))
        assert len(pop.get_all()) == 2

    def test_richest_agent(self, sample_manifest, hermes_manifest):
        pop = EconomicPopulation()
        a1 = EconomicAgent(sample_manifest, initial_wealth=100.0)
        a2 = EconomicAgent(hermes_manifest, initial_wealth=200.0)
        pop.add_agent(a1)
        pop.add_agent(a2)
        richest = pop.get_richest_agent()
        assert richest is a2

    def test_get_best_agents(self, sample_manifest, hermes_manifest):
        pop = EconomicPopulation()
        a1 = EconomicAgent(sample_manifest, initial_wealth=100.0)
        a2 = EconomicAgent(hermes_manifest, initial_wealth=200.0)
        pop.add_agent(a1)
        pop.add_agent(a2)
        best = pop.get_best_agents(n=1)
        assert len(best) == 1
        assert best[0] is a2


# ════════════════════════════════════════════════════════════════
# Test Auctioneer
# ════════════════════════════════════════════════════════════════

class TestAuctioneer:
    def test_auction_selects_winner(self, economy_config, sample_manifest, hermes_manifest):
        """Auction should select a winner among candidates."""
        pop = EconomicPopulation()
        agent_a = EconomicAgent(sample_manifest, initial_wealth=100.0)
        agent_b = EconomicAgent(hermes_manifest, initial_wealth=100.0)
        pop.add_agent(agent_a)
        pop.add_agent(agent_b)

        auctioneer = Auctioneer()
        winner, payment = auctioneer.run_auction(
            active_agents=[agent_a, agent_b],
            bid_scheme="fixed",
            engine_config=economy_config.engine,
            training=True,
        )
        assert winner is not None
        assert winner in (agent_a, agent_b)
        assert payment > 0

    def test_auction_no_candidates(self, economy_config):
        auctioneer = Auctioneer()
        with pytest.raises(ValueError):
            # Empty list causes max() on empty sequence
            auctioneer.run_auction(
                active_agents=[],
                bid_scheme="fixed",
                engine_config=economy_config.engine,
                training=True,
            )

    def test_auction_payment_deducted(self, economy_config, sample_manifest):
        """Winner's payment should be deducted from wealth via process_payment."""
        pop = EconomicPopulation()
        agent = EconomicAgent(sample_manifest, initial_wealth=100.0)
        pop.add_agent(agent)

        auctioneer = Auctioneer()
        winner, payment = auctioneer.run_auction(
            active_agents=[agent],
            bid_scheme="fixed",
            engine_config=economy_config.engine,
            training=True,
        )
        assert winner is agent
        assert payment > 0
        # Payment is deducted via process_payment, not in run_auction
        auctioneer.process_payment(winner, payment, prev_winner=None)
        assert agent.wealth < 100.0


# ════════════════════════════════════════════════════════════════
# Test EconomicRouter
# ════════════════════════════════════════════════════════════════

class TestEconomicRouter:
    def test_register_creates_economic_agent(self, economic_router, sample_manifest):
        """Agents register in the economy."""
        agent = economic_router.register(sample_manifest)
        assert isinstance(agent, EconomicAgent)
        assert agent.manifest.tether_id == "test-agent-001"
        assert agent.wealth == 100.0

    def test_register_also_in_router(self, economic_router, sample_manifest):
        """Agents are also registered in the underlying TetherRouter."""
        economic_router.register(sample_manifest)
        assert economic_router.get("test-agent-001") is sample_manifest

    def test_unregister_removes_from_economy(self, economic_router, sample_manifest):
        economic_router.register(sample_manifest)
        economic_router.unregister("test-agent-001")
        assert economic_router.get("test-agent-001") is None
        assert economic_router.get_economic_agent("test-agent-001") is None

    def test_discover_works(self, economic_router, sample_manifest):
        """Capability-based discovery still works."""
        economic_router.register(sample_manifest)
        results = economic_router.discover("code_review")
        assert len(results) >= 1
        assert results[0].tether_id == "test-agent-001"

    def test_route_economic_mode(self, economic_router, sample_manifest, hermes_manifest):
        """Economic routing selects via auction."""
        economic_router.register(sample_manifest)
        economic_router.register(hermes_manifest)

        task = TetherTask(
            task_id="t-001",
            task_type="code_review",
            input_data={"code": "print('hello')"},
            source_agent="user",
            source_protocol=Protocol.A2A,
        )

        result = economic_router.route(task)
        assert result is not None
        assert result.tether_id in ("test-agent-001", "hermes-agent-001")

    def test_route_capability_mode(self, economic_router, sample_manifest, hermes_manifest):
        """Capability mode falls back to TetherRouter behavior."""
        economic_router.mode = "capability"
        economic_router.register(sample_manifest)
        economic_router.register(hermes_manifest)

        task = TetherTask(
            task_id="t-002",
            task_type="code_review",
            input_data={},
            source_agent="user",
            source_protocol=Protocol.A2A,
        )

        result = economic_router.route(task)
        assert result is not None
        assert result.tether_id in ("test-agent-001", "hermes-agent-001")

    def test_route_no_candidates(self, economic_router):
        """Route with no matching agents returns None."""
        task = TetherTask(
            task_id="t-003",
            task_type="nonexistent_task",
            input_data={},
            source_agent="user",
            source_protocol=Protocol.A2A,
        )
        result = economic_router.route(task)
        assert result is None

    def test_apply_reward(self, economic_router, sample_manifest):
        """Reward increases agent wealth."""
        economic_router.register(sample_manifest)
        reward = economic_router.apply_reward("test-agent-001", 25.0)
        assert reward == 25.0
        assert economic_router.get_wealth("test-agent-001") == 125.0

    def test_apply_reward_default(self, economic_router, sample_manifest):
        """Default reward uses config value."""
        economic_router.register(sample_manifest)
        reward = economic_router.apply_reward("test-agent-001")
        assert reward == 10.0  # Default task_reward
        assert economic_router.get_wealth("test-agent-001") == 110.0

    def test_wealth_distribution(self, economic_router, sample_manifest, hermes_manifest):
        economic_router.register(sample_manifest)
        economic_router.register(hermes_manifest)
        dist = economic_router.get_wealth_distribution()
        assert len(dist) == 2
        assert dist["test-agent-001"] == 100.0
        assert dist["hermes-agent-001"] == 100.0

    def test_mode_switching(self, economic_router):
        assert economic_router.mode == "economic"
        economic_router.mode = "capability"
        assert economic_router.mode == "capability"
        with pytest.raises(ValueError):
            economic_router.mode = "invalid"

    def test_list_agents(self, economic_router, sample_manifest, hermes_manifest):
        economic_router.register(sample_manifest)
        economic_router.register(hermes_manifest)
        agents = economic_router.list_agents()
        assert len(agents) == 2

    def test_get_stats(self, economic_router, sample_manifest):
        economic_router.register(sample_manifest)
        stats = economic_router.get_stats()
        assert "episode_count" in stats
        assert "population_size" in stats
        assert stats["population_size"] == 1


# ════════════════════════════════════════════════════════════════
# Test Mesh with EconomicRouter
# ════════════════════════════════════════════════════════════════

class TestMeshEconomy:
    def test_mesh_creates_economic_router(self):
        """Mesh should use EconomicRouter by default."""
        mesh = Mesh()
        assert isinstance(mesh.router, EconomicRouter)
        assert mesh.router.mode == "economic"

    def test_mesh_register_adds_to_economy(self, sample_manifest):
        mesh = Mesh()
        mesh.register(sample_manifest)
        wealth = mesh.get_wealth("test-agent-001")
        assert wealth == 100.0

    def test_mesh_wealth_distribution(self, sample_manifest, hermes_manifest):
        mesh = Mesh()
        mesh.register(sample_manifest)
        mesh.register(hermes_manifest)
        dist = mesh.get_wealth_distribution()
        assert len(dist) == 2

    def test_mesh_get_economic_agent(self, sample_manifest):
        mesh = Mesh()
        mesh.register(sample_manifest)
        agent = mesh.get_economic_agent("test-agent-001")
        assert agent is not None
        assert agent.wealth == 100.0

    def test_mesh_economy_stats(self, sample_manifest):
        mesh = Mesh()
        mesh.register(sample_manifest)
        stats = mesh.get_economy_stats()
        assert "episode_count" in stats
        assert "population_size" in stats

    def test_mesh_set_economy_mode(self):
        mesh = Mesh()
        assert mesh.router.mode == "economic"
        mesh.set_economy_mode("capability")
        assert mesh.router.mode == "capability"

    def test_mesh_capability_mode_register(self, sample_manifest):
        """Mesh in capability mode should still register agents."""
        mesh = Mesh(mode="capability")
        assert mesh.router.mode == "capability"
        mesh.register(sample_manifest)
        assert mesh.router.get("test-agent-001") is sample_manifest

    def test_mesh_discover_works(self, sample_manifest):
        mesh = Mesh()
        mesh.register(sample_manifest)
        result = mesh.discover("code_review")
        assert result is not None
        assert result.tether_id == "test-agent-001"

    def test_mesh_discover_all(self, sample_manifest, hermes_manifest):
        mesh = Mesh()
        mesh.register(sample_manifest)
        mesh.register(hermes_manifest)
        results = mesh.discover_all("code_review")
        assert len(results) >= 1

    def test_mesh_list_agents(self, sample_manifest):
        mesh = Mesh()
        mesh.register(sample_manifest)
        agents = mesh.list_agents()
        assert len(agents) == 1


# ════════════════════════════════════════════════════════════════
# Test EconomicEngine
# ════════════════════════════════════════════════════════════════

class TestEconomicEngine:
    def test_engine_register(self, economy_config, sample_manifest):
        engine = EconomicEngine(config=economy_config)
        agent = engine.register_agent(sample_manifest)
        assert agent.wealth == 100.0

    def test_engine_auction(self, economy_config, sample_manifest, hermes_manifest):
        engine = EconomicEngine(config=economy_config)
        engine.register_agent(sample_manifest)
        engine.register_agent(hermes_manifest)

        winner_id, payment = engine.run_auction(
            task_type="code_review",
            candidates=[sample_manifest, hermes_manifest],
        )
        assert winner_id is not None
        assert winner_id in ("test-agent-001", "hermes-agent-001")
        assert payment > 0

    def test_engine_apply_reward(self, economy_config, sample_manifest):
        engine = EconomicEngine(config=economy_config)
        engine.register_agent(sample_manifest)
        engine.apply_reward("test-agent-001", 15.0)
        assert engine.get_agent_wealth("test-agent-001") == 115.0

    def test_engine_wealth_distribution(self, economy_config, sample_manifest, hermes_manifest):
        engine = EconomicEngine(config=economy_config)
        engine.register_agent(sample_manifest)
        engine.register_agent(hermes_manifest)
        dist = engine.get_wealth_distribution()
        assert len(dist) == 2

    def test_engine_serialize(self, economy_config, sample_manifest):
        engine = EconomicEngine(config=economy_config)
        engine.register_agent(sample_manifest)
        data = engine.serialize_settings()
        assert "config" in data
        assert "stats" in data
        assert data["stats"]["episodes"] == 0
