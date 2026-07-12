# Model Routing & Pricing

## Pricing Oracle

The PricingOracle (adapted from NecroSwarm's CostRouter) provides bid suggestions based on task complexity and model cost.

### 33 Validated Models

#### T1 (HIGH) — Complex synthesis, code, deep reasoning

| Model | Cost/1K tokens | Latency | Capabilities |
|-------|----------------|---------|-------------|
| kimi-k2.5:cloud | $0.005 | 2000ms | reasoning, code, analysis, synthesis, complex_planning |
| deepseek-v3.1:671b:cloud | $0.004 | 2500ms | reasoning, code, analysis, deep_thinking |
| glm-5.1:cloud | $0.003 | 1500ms | reasoning, code, analysis, general |
| qwen3-coder:480b:cloud | $0.004 | 2200ms | code, reasoning, debugging, architecture |
| mistral-large-3:675b:cloud | $0.004 | 2400ms | reasoning, analysis, synthesis |
| cogito-2.1:671b:cloud | $0.004 | 2300ms | reasoning, deep_analysis, strategy |
| nemotron-3-super:cloud | $0.003 | 1800ms | reasoning, analysis, code |

#### T2 (MEDIUM) — Analysis, validation, research

| Model | Cost/1K tokens | Latency | Capabilities |
|-------|----------------|---------|-------------|
| minimax-m2.5:cloud | $0.0015 | 1000ms | reasoning, analysis, research, balanced |
| minimax-m2.7:cloud | $0.0015 | 1000ms | reasoning, analysis, research |
| qwen3-vl:235b:cloud | $0.002 | 1500ms | vision, reasoning, multimodal |
| gemma4:31b:cloud | $0.001 | 800ms | reasoning, analysis, general |
| devstral-2:123b:cloud | $0.002 | 1200ms | code, development, debugging |

#### T3 (LOW) — Formatting, simple transforms, cost savings

| Model | Cost/1K tokens | Latency | Capabilities |
|-------|----------------|---------|-------------|
| gemma3:27b:cloud | $0.0005 | 600ms | basic, formatting, simple_reasoning |
| gemma3:12b:cloud | $0.0003 | 400ms | basic, formatting |
| gemma3:4b:cloud | $0.0001 | 300ms | basic, formatting |
| ministral-3:8b:cloud | $0.0002 | 350ms | basic, formatting, simple_reasoning |
| ministral-3:3b:cloud | $0.0001 | 250ms | basic, formatting |
| nemotron-3-nano:30b:cloud | $0.0003 | 400ms | basic, formatting, simple_reasoning |
| devstral-small-2:24b:cloud | $0.0005 | 500ms | code, basic_development |

#### Think — Extended reasoning

| Model | Cost/1K tokens | Latency | Capabilities |
|-------|----------------|---------|-------------|
| kimi-k2:1t:cloud | $0.006 | 5000ms | extended_reasoning, deep_analysis, planning |
| kimi-k2-thinking:cloud | $0.007 | 6000ms | extended_reasoning, deep_analysis, strategy |

### Bid Suggestion Algorithm

The PricingOracle.estimate_bid() uses:
1. Task complexity (trivial/simple/moderate/complex)
2. Estimated token count
3. Model cost per token
4. A profit margin multiplier (default 1.2x cost)

This ensures bids reflect actual compute costs, preventing wealth inflation or starvation.
