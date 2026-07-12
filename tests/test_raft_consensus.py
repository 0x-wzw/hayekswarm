"""Regression tests for Raft consensus fixes (issues #5, #6).

- #5: leader election must actually count votes and elect a single leader.
- #6: a leader must not commit a previous-term entry by replica count alone
  (Raft Figure-8 safety); persistent state must survive a restart.
"""

from __future__ import annotations

import asyncio

import pytest

from swarm.consensus.raft import RaftProtocol, NodeState, RaftLogEntry


class InMemoryRaft(RaftProtocol):
    """RaftProtocol wired to an in-memory message bus for testing."""

    _nodes: dict | None = None

    async def _send_message(self, peer: str, msg) -> None:
        node = (self._nodes or {}).get(peer)
        if node is not None:
            node.receive_message(msg)


@pytest.mark.asyncio
async def test_multinode_elects_single_leader():
    ids = ["n1", "n2", "n3"]
    nodes: dict[str, InMemoryRaft] = {}
    for nid in ids:
        n = InMemoryRaft(
            nid,
            [p for p in ids if p != nid],
            election_timeout_min=0.05,
            election_timeout_max=0.12,
            heartbeat_interval=0.02,
        )
        n._nodes = nodes
        nodes[nid] = n

    for n in nodes.values():
        await n.start()
    try:
        # Give the cluster time to hold an election and stabilize.
        await asyncio.sleep(0.8)
        leaders = [n for n in nodes.values() if n.state == NodeState.LEADER]
        assert len(leaders) == 1, f"expected exactly one leader, got {len(leaders)}"
        # Everyone else is a follower and agrees on the (higher) term.
        leader = leaders[0]
        for n in nodes.values():
            if n is not leader:
                assert n.state == NodeState.FOLLOWER
    finally:
        for n in nodes.values():
            await n.stop()


@pytest.mark.asyncio
async def test_commit_requires_current_term():
    n = RaftProtocol("n1", ["n2", "n3"])
    n.state = NodeState.LEADER
    n.current_term = 2

    # A leftover entry from an earlier term, replicated to a majority.
    n.log = [RaftLogEntry(index=1, term=1, command="x")]
    n.match_index = {"n2": 1, "n3": 1}
    await n._check_commit()
    assert n.commit_index == 0, "must not commit a previous-term entry by count alone"

    # Appending a current-term entry that reaches a majority commits it, and the
    # earlier entry commits indirectly along with it.
    n.log.append(RaftLogEntry(index=2, term=2, command="y"))
    n.match_index = {"n2": 2, "n3": 2}
    await n._check_commit()
    assert n.commit_index == 2


@pytest.mark.asyncio
async def test_persistent_state_survives_restart(tmp_path):
    path = str(tmp_path / "raft-n1.json")

    n = RaftProtocol("n1", ["n2", "n3"], storage_path=path)
    n.current_term = 5
    n.voted_for = "n2"
    n.log = [RaftLogEntry(index=1, term=5, command="cmd")]
    n._persist_state()

    # Simulate a restart: a fresh node restores from the same path.
    restarted = RaftProtocol("n1", ["n2", "n3"], storage_path=path)
    assert restarted.current_term == 5
    assert restarted.voted_for == "n2"
    assert len(restarted.log) == 1 and restarted.log[0].term == 5
