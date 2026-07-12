"""Regression tests for the voidtether.economy fixes (issue #8).

Covers: bad-birth replacement spawning, bucket-brigade payment conservation,
same-agent consecutive-win handling, and the get_best_agents(role=...) deadlock.
"""

from __future__ import annotations

import threading

from voidtether.core.manifest import TetherManifest, Protocol
from voidtether.economy import (
    Auctioneer,
    EconomicAgent,
    EconomicEngine,
    EconomicPopulation,
    EconomyConfig,
    EngineConfig,
    EvolutionConfig,
)


def _manifest(tether_id: str, name: str) -> TetherManifest:
    return TetherManifest(
        tether_id=tether_id,
        name=name,
        origin_protocol=Protocol.A2A,
        capabilities={"tasks": ["x"]},
    )


def test_bad_birth_spawns_replacement_not_collapse():
    # p_b=1.0 => every bankruptcy triggers a bad-birth. Before the fix the
    # source lookup missed (agents already removed) and the population collapsed.
    cfg = EconomyConfig(
        engine=EngineConfig(initial_wealth=1.0, max_num_agents=0),
        evolution=EvolutionConfig(p_a=0.0, p_b=1.0),
    )
    engine = EconomicEngine(cfg)
    engine.set_agent_factory(
        birth_good_agent=lambda parent: EconomicAgent(manifest=parent.manifest, initial_wealth=1.0),
        birth_bad_agent=lambda source, **kw: EconomicAgent(manifest=source.manifest, initial_wealth=1.0),
    )

    a = engine.register_agent(_manifest("a1", "A-1"))
    assert len(engine.population) == 1

    a.wealth = -1.0  # drive bankrupt
    removed = engine.check_bankruptcies()
    assert removed == ["a1"]
    assert len(engine.population) == 0

    engine.spawn_replacements(removed)
    assert len(engine.population) == 1, "bad-birth must spawn a replacement"


def test_bucket_brigade_conserves_money():
    au = Auctioneer()
    a = EconomicAgent(manifest=_manifest("a1", "A-1"), initial_wealth=1.0)
    b = EconomicAgent(manifest=_manifest("b1", "B-1"), initial_wealth=1.0)

    # First action in a chain: payment goes to the void.
    au.process_payment(a, 0.3, prev_winner=None)
    assert round(a.wealth, 5) == 0.7

    # B (winner) pays its bid to A (previous winner): money conserved.
    total_before = a.wealth + b.wealth
    au.process_payment(b, 0.4, prev_winner=a)
    assert round(b.wealth, 5) == 0.6
    assert round(a.wealth, 5) == 1.1
    assert round(a.wealth + b.wealth, 5) == round(total_before, 5)


def test_same_agent_consecutive_win_nets_zero():
    au = Auctioneer()
    a = EconomicAgent(manifest=_manifest("a1", "A-1"), initial_wealth=1.0)
    before = a.wealth
    # Winner pays itself (won two steps running): no money should be destroyed.
    au.process_payment(a, 0.5, prev_winner=a)
    assert a.wealth == before


def test_get_best_agents_by_role_does_not_deadlock():
    pop = EconomicPopulation()
    a = EconomicAgent(manifest=_manifest("a1", "A-1"), initial_wealth=1.0)
    pop.add_agent(a)

    result: dict = {}

    def call():
        result["r"] = pop.get_best_agents(role=a.role)

    t = threading.Thread(target=call)
    t.start()
    t.join(timeout=3)
    assert not t.is_alive(), "get_best_agents(role=...) deadlocked"
    assert result["r"] and result["r"][0] is a
