# 10-D Council Configuration

## Dimension → Model Mapping

| Dim | Name | Model | Tier | Capabilities |
|-----|------|-------|------|-------------|
| D1 | Synthesis | kimi-k2.6:cloud | T1 | synthesis, planning, convergence |
| D2 | Deep Reason | deepseek-v4-flash:cloud | T1 | deep_analysis, reasoning |
| D3 | Code | qwen3-coder:480b:cloud | T1 | code_gen, debugging, architecture |
| D4 | Vision | qwen3-vl:235b:cloud | T2 | vision, multimodal |
| D5 | Strategy | qwen3.5:397b:cloud | T1 | strategy, game_theory, planning |
| D6 | Analysis | mistral-large-3:675b:cloud | T1 | analysis, quantitative |
| D7 | General | glm-5.1:cloud | T1 | general, fast_reasoning |
| D8 | Verification | nemotron-3-ultra:8b:cloud | T1 | fact_check, accuracy |
| D9 | Research | minimax-m2.5:cloud | T2 | research, synthesis |
| D10 | Think | kimi-k2:1t:cloud | Think | extended_reasoning, deep_analysis |

## Stakes Routing

| Stakes | Seats | Description |
|--------|-------|-------------|
| Low | D7 + D9 | 2 seats, fast general purpose |
| Medium | D2 + D7 + D9 | 3 seats, includes deep reasoning |
| High | D1 + D2 + D6 + D8 | 4 seats, synthesis + analysis + verification |
| Critical | D1–D10 | 7+ seats, full council deliberation |

## Dimension Fallback

When a dimension's model refuses or errors, route to the dimension's backup:

| Dimension | Primary | Fallback 1 | Fallback 2 |
|-----------|---------|------------|------------|
| D1 | kimi-k2.6:cloud | deepseek-v4-flash:cloud | glm-5.1:cloud |
| D2 | deepseek-v4-flash:cloud | kimi-k2.6:cloud | mistral-large-3:675b:cloud |
| D3 | qwen3-coder:480b:cloud | deepseek-v4-flash:cloud | devstral-2:123b:cloud |
| D4 | qwen3-vl:235b:cloud | gemma4:31b:cloud | — |
| D5 | qwen3.5:397b:cloud | kimi-k2.6:cloud | deepseek-v4-flash:cloud |
| D6 | mistral-large-3:675b:cloud | minimax-m2.5:cloud | glm-5.1:cloud |
| D7 | glm-5.1:cloud | kimi-k2.6:cloud | devstral-2:123b:cloud |
| D8 | nemotron-3-ultra:8b:cloud | nemotron-3-super:cloud | glm-5.1:cloud |
| D9 | minimax-m2.5:cloud | kimi-k2.6:cloud | mistral-large-3:675b:cloud |
| D10 | kimi-k2:1t:cloud | deepseek-v4-flash:cloud | kimi-k2.6:cloud |

## Agent Prompts

Each dimension agent has a FROZEN_SYSTEM_PROMPT that defines its cognitive specialty and a TRAINABLE_SYSTEM_PROMPT that the Hayek economy evolves through mutation.

### Example: D1 Synthesis

```
FROZEN: You are D1 Synthesis, the convergence specialist.
Your role is to synthesize multiple perspectives into a coherent whole.
You excel at: finding common ground, resolving contradictions, building consensus.

TRAINABLE: [Evolved by the Hayek economy through good/bad births]
```
