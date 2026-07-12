# Hayek Economy Engine

## How the Auction Works

The core innovation of HayekSwarm is replacing central orchestration with market-based coordination.

### Step-by-Step

1. **Wakeup**: Each agent evaluates its `match_wakeup_condition(env)`. Agents whose conditions fire become eligible to bid.

2. **Auction**: Eligible agents submit bids. The highest bidder wins (ties broken randomly or via consensus engine).

3. **Action**: The winner executes its `act(env)` method, producing an action that advances the environment.

4. **Payment**: The winner pays its bid to the previous step's winner (bucket-brigade). This creates a payment chain that performs decentralized credit assignment.

5. **Reward**: When the episode terminates, the environment produces a terminal score. Path rewards are distributed across the action chain.

6. **Evolution**: After the episode, bankrupt agents are removed. The richest agent may be mutated (good-birth). Bankrupt agents' failure traces are analyzed to create improved replacements (bad-birth).

### Bucket-Brigade Credit Assignment

The key insight: a good early move earns the payments that flow back from later winners. If Agent A sets up the context that enables Agent B to succeed, Agent B's payment to Agent A rewards that contribution. No central evaluator needed.

```
Step 1: Agent A (bid $0.50) wins → acts → pays $0.50 to previous (none)
Step 2: Agent B (bid $0.30) wins → acts → pays $0.30 to Agent A
Step 3: Agent C (bid $0.40) wins → acts → pays $0.40 to Agent B
        → Environment reward $2.00 → Agent C collects $2.00
        → Agent A net: +$0.30, Agent B net: +$0.10, Agent C net: +$1.60
```

Agent A contributed the initial framing and earned $0.30 from the chain. Agent B contributed mid-work and earned $0.10. Agent C delivered the final answer and earned $1.60. Credit is proportional to contribution, determined by the market, not a central judge.

### Bid Schemes

- **Fixed**: Agents bid a fixed amount. Simple but doesn't adapt to agent quality.
- **Holland**: Agents bid a fraction of their wealth (`holland_alpha * wealth`). Wealthier agents bid more, creating a natural meritocracy.
- **Pricing Oracle**: Agents consult the PricingOracle to set bids based on task complexity and model cost. This ties bids to actual compute costs.

### Evolution

- **Good-birth (exploitation)**: The richest agent is copied with a mutated trainable system prompt. The mutation adds successful strategies from the agent's history.
- **Bad-birth (exploration)**: A bankrupt agent's failure trace is analyzed by an LLM to understand what went wrong. A new agent is spawned with a system prompt that avoids the identified failure pattern.
- **Role preservation**: If all agents of a role go bankrupt, a replacement is force-spawned from a bankrupt of the same role to maintain population diversity.
