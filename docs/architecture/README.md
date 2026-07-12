# HayekSwarm — Architecture Overview

## The Synthesis

HayekSwarm unifies three lineages into one coherent system:

```
EoM (arXiv:2606.02859)          NecroSwarm (0x-wzw)          NeuroSwarm (0x-wzw)
    │                                │                            │
    │ HayekMAS engine                 │ 10-D Council               │ Dual-phase dispatch
    │ Auction loop                    │ Cost router (33 models)    │ Signal detection
    │ Bucket-brigade payments         │ Raft consensus             │ Dimension-aware fallback
    │ Population evolution            │ Docker sandbox             │ Honcho-adapter bridge
    │ Training pipeline               │ FRIDAY skill system        │ Pre-spawn analysis
    │ 5 domain adapters               │ 24 skills                  │
    │ Published results               │ Next.js + Vue frontend     │
    │                                │ CI/CD                      │
    └──────────┬────────────────────┘ └──────────┬─────────────────┘
               │                                 │
               └──────────────┬──────────────────┘
                              │
                              ▼
                     HAYEKSWARM v1.0.0
              Decentralized multi-agent intelligence
              through Hayekian market economics
```

## Core Architecture

### Layer 1: Hayek Economy (`hayekmas/`)

The economic engine. Manages agent populations, auctions, payments, and evolution.

**Key Components:**
- `HayekMAS` — Core execution engine. Runs the auction-action loop, applies path rewards, handles bankruptcies and births.
- `BaseAgent` — Abstract agent with wealth, bids, prompts, bankruptcy detection, lineage tracking.
- `BaseEnv` — Abstract environment with action history, termination detection, scoring.
- `Population` — Agent membership store with role indexing, wakeup matching, parent selection.
- `Trainer` — Training pipeline with checkpointing, resume support, periodic evaluation.

**The Auction Loop:**
1. Each step: evaluate all agents' wakeup conditions
2. Eligible agents bid (fixed or wealth-proportional)
3. Highest bidder wins, executes action
4. Winner pays bid to previous actor (bucket-brigade)
5. Environment reward collected by final actor
6. Path reward distributed across the action chain

**Evolution:**
- After each episode, bankrupt agents are removed
- Good-birth: richest agent is copied with mutation (exploitation)
- Bad-birth: bankrupt agent's failure trace is analyzed to create improved replacement (exploration)
- Role preservation: if a role goes extinct, it's force-spawned from a bankrupt of the same role

### Layer 2: Swarm Infrastructure (`swarm/`)

The model and infrastructure layer. Provides the agents that participate in the economy.

**Key Components:**
- `Council` — 10-D agent population manager. Creates, tracks, and mutates dimension-specialized agents.
- `CouncilAgent` (D1-D10) — Concrete BaseAgent subclasses with dimension-specific prompts and model assignments.
- `PricingOracle` — Cost router adapted as a bid-pricing service. 33 validated models across 4 tiers.
- `ConsensusEngine` — Weighted majority, Borda count, Delphi method for resolving auction ties and validating outcomes.
- `RaftProtocol` — Full Raft consensus for distributed leader election and log replication.
- `SwarmCoordinator` — Agent lifecycle management with Docker sandbox integration.
- `DockerSandbox` — Tiered resource allocation (T1/T2/T3) for ephemeral agents.

### Layer 3: Skills & Frontend

The production surface. 24 skills, Next.js dashboard, Vue 3 UI.

## Data Flow

```
User Task
    │
    ▼
┌─────────────────────────────────────────────┐
│  HayekMAS.run_one_episode(env)               │
│                                              │
│  ┌─────────┐   ┌──────────┐   ┌──────────┐  │
│  │ Step 1  │──>│ Step 2   │──>│ Step N   │  │
│  │ Auction │   │ Auction  │   │ Auction  │  │
│  └────┬────┘   └────┬─────┘   └────┬─────┘  │
│       │              │              │         │
│       ▼              ▼              ▼         │
│  ┌─────────┐   ┌──────────┐   ┌──────────┐  │
│  │ D2 wins │   │ D1 wins  │   │ D7 wins  │  │
│  │ $0.40   │   │ $0.30    │   │ $0.20    │  │
│  └────┬────┘   └────┬─────┘   └────┬─────┘  │
│       │              │              │         │
│       ▼              ▼              ▼         │
│  ┌─────────────────────────────────────────┐  │
│  │  Bucket-Brigade Payment Chain           │  │
│  │  D2 pays $0.40 → D1 pays $0.30 → D7   │  │
│  │  Environment reward $2.00 → D7         │  │
│  │  Net: D2 +$0.30, D1 +$0.10, D7 +$1.60│  │
│  └─────────────────────────────────────────┘  │
│                                              │
│  ┌─────────────────────────────────────────┐  │
│  │  Post-Episode Evolution                 │  │
│  │  • Remove bankrupt agents                │  │
│  │  • Good-birth: mutate richest agent     │  │
│  │  • Bad-birth: analyze failure, spawn    │  │
│  └─────────────────────────────────────────┘  │
└─────────────────────────────────────────────┘
```

## Configuration

See `hayekmas/base/config.py` for the full configuration schema.

Key parameters:
- `engine.max_steps_per_episode` — Max steps before forced termination
- `engine.base_bid` — Default bid for new agents
- `engine.initial_wealth` — Starting wealth for new agents
- `engine.bid_scheme` — "fixed" or "holland" (wealth-proportional)
- `engine.holland_alpha` — Fraction of wealth used as bid in Holland scheme
- `evolution.p_a` — Probability of good-birth after bankruptcy
- `evolution.p_b` — Probability of bad-birth after bankruptcy
- `reward.path_reward_scale` — Scale factor for path rewards
- `reward.center_env_reward` — Whether to center rewards around zero
