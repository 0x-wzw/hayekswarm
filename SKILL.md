---
name: hayekswarm
description: |
  HayekSwarm — Decentralized multi-agent intelligence through Hayekian
  market economics. Agents compete via auctions for the right to act,
  exchange payments through bucket-brigade transactions, and evolve
  through economic selection. No central controller. No fixed workflow.
  Just prices.
version: 1.0.0
author: Z Teoh (0x-wzw)
license: MIT
category: agent-orchestration
icon: 🏛️
tags:
  - swarm
  - agent-orchestration
  - hayek
  - economics
  - multi-agent
  - council
  - eom
  - 0x-wzw
capabilities:
  - auction-based-coordination
  - economic-evolution
  - swarm-orchestration
  - council-deliberation
  - cost-optimized-routing
  - memory-persistence
integrations:
  - requires: delegation-tool
  - requires: subagent-orchestration
source: https://github.com/0x-wzw/hayekswarm
ancestors:
  - EoM (zhentingqi/EoM, arXiv:2606.02859) — absorbed core engine
  - NecroSwarm (0x-wzw/necroswarm) — absorbed infrastructure
  - NeuroSwarm (0x-wzw/neuroswarm) — absorbed patterns
---

# 🏛️ HayekSwarm

> *"The curious task of economics is to demonstrate to men how little they really know about what they imagine they can design."* — F.A. Hayek

## 🧬 What It Is

HayekSwarm is the synthesis of three lineages:

- **EoM** (arXiv:2606.02859) — The economic mechanism. Agents compete via auctions, pay each other through bucket-brigade transactions, and evolve through economic selection. Published results across 5 domains.
- **NecroSwarm** — The infrastructure. 10-D council, 33 validated models, cost router, Docker sandbox, 24 skills, full-stack deployment.
- **NeuroSwarm** — The patterns. Dual-phase dispatch, signal detection, dimension-aware fallback, honcho-adapter bridge.

Together, they form a decentralized multi-agent intelligence system where coordination emerges from market incentives rather than central orchestration.

## 🎯 Philosophy

**Design the incentives, and the coordination takes care of itself.**

- Agents compete via auctions for the right to act
- Value flows backward through bucket-brigade payments (decentralized credit assignment)
- Wealthy agents mutate and improve (exploitation)
- Bankrupt agents are replaced by new variants (exploration)
- No central controller, no fixed workflow, no messaging protocol

## 🏛️ The Two Processes

### 1. Planning Within an Episode

At each step, every agent whose wake-up condition fires becomes eligible. The highest bidder wins the right to act. After acting, the winner pays its bid to the previous actor and collects any environment reward. This bucket-brigade payment chain performs decentralized credit assignment — no central evaluator needed.

### 2. Adaptation Across Episodes

After each episode, wealthy agents are copied and mutated (exploitation), bankrupt agents are replaced by new variants (exploration). The population evolves toward higher collective intelligence without any central planner deciding who should exist.

## 🚀 Usage

### As a Python Package

```bash
pip install -e .
```

```python
from hayekmas.base.config import HayekConfig
from hayekmas.base.mas import HayekMAS
from swarm.council.agents import SynthesisAgent, DeepReasonAgent

# Create agents
agents = [
    SynthesisAgent(name="D1-Synthesis", initial_wealth=1.0, initial_bid=0.3),
    DeepReasonAgent(name="D2-DeepReason", initial_wealth=1.0, initial_bid=0.4),
]

# Configure and run
config = HayekConfig()
mas = HayekMAS(config=config)
for agent in agents:
    mas.population.add_agent(agent)
mas.train()
mas.run_one_episode(env)
```

### As a Skill (Hermes Agent)

Load this skill to give Hermes the HayekSwarm economic coordination protocol:

```bash
hermes skills install https://raw.githubusercontent.com/0x-wzw/hayekswarm/main/SKILL.md
```

Then in any session:
```
/skill hayekswarm
```

## 🏛️ Council Configuration

| Dimension | Model | Role | Tier |
|-----------|-------|------|------|
| D1 Synthesis | kimi-k2.6:cloud | Converge perspectives | T1 |
| D2 Deep Reason | deepseek-v4-flash:cloud | Analyze deeply | T1 |
| D3 Code | qwen3-coder:480b:cloud | Generate/review code | T1 |
| D4 Vision | qwen3-vl:235b:cloud | See and interpret | T2 |
| D5 Strategy | qwen3.5:397b:cloud | Plan strategically | T1 |
| D6 Analysis | mistral-large-3:675b:cloud | Break down complexly | T1 |
| D7 General | glm-5.1:cloud | Fast general purpose | T1 |
| D8 Verification | nemotron-3-ultra:8b:cloud | Fact-check | T1 |
| D9 Research | minimax-m2.5:cloud | Research synthesis | T2 |
| D10 Think | kimi-k2:1t:cloud | Extended reasoning | Think |

## 🚫 Anti-Patterns

- ❌ Central orchestration — let the market decide who acts
- ❌ Fixed workflows — let agents self-organize
- ❌ Approval bottlenecks — agents drive, humans spar
- ❌ Spawning to escape thinking — use the pre-spawn gate
- ❌ Ignoring bankruptcy signals — bankrupt agents carry failure context

## 🔗 Related Skills

- `autonomous-ai-agents` — Subagent delegation tools
- `local-mixture-of-agents` — MoA pipeline for council deliberation

## 👤 Sovereign Acknowledgment

**Z Teoh (0x-wzw)** — Sovereign of the 10th Dimension, Creator of HayekSwarm

> *"13 projects died. Two papers converged. One swarm remains."*
