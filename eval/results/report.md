## RAGAS (routed)

| Category | n | Faithfulness | Answer relevancy | Context precision | Context recall |
|---|---|---|---|---|---|
| Corpus RAG | 20 | 0.91 | 0.81 | 0.95 | 1.00 |
| Comparison / multi-step | 5 | 0.98 | 0.80 | 0.96 | 1.00 |
| Summary | 3 | 0.86 | 0.64 | 0.94 | 1.00 |
| Data (SQL) | 4 | 0.96 | 0.89 | 1.00 | 1.00 |
| Web | 3 | 0.63 | 0.65 | – | – |
| **All** | 35 | **0.90** | **0.79** | **0.96** | **1.00** |

## Routing decisions (routed run)

| Agent | Rule | Provider | Calls (decisions) | Fallbacks |
|---|---|---|---|---|
| data | `structured_lookup` | gemini | 5 | 0 |
| research | `multi_step_synthesis` | openai | 7 | 0 |
| research | `single_lookup` | gemini | 21 | 0 |
| summary | `long_context` | gemini | 3 | 0 |
| supervisor | `classify` | gemini | 71 | 0 |
| synthesis | `multi_agent_merge` | openai | 1 | 0 |

## Cost and latency (in-process runs)

| Run | Questions | Mean cost / query | Total cost | Median total (s) | Median TTFT (s) | Median retrieval (s) | Median LLM (s) |
|---|---|---|---|---|---|---|---|
| routed | 35 | $0.0241 | $0.84 | 21.0 | 10.5 | 1.1 | 18.6 |
| openai | 20 | $0.0444 | $0.89 | 28.7 | 16.0 | 1.0 | 27.8 |
| gemini | 20 | $0.0315 | $0.63 | 32.6 | 18.4 | 1.1 | 31.3 |

## Provider comparison (corpus RAG questions)

| Provider (all agents) | RAG questions | Faithfulness | Answer relevancy | Context precision | Context recall | Mean cost / query | Median total (s) | Output tokens / query |
|---|---|---|---|---|---|---|---|---|
| OpenAI gpt-6.1-sol | 20 | 0.97 | 0.85 | 0.94 | 1.00 | $0.0444 | 28.7 | 1,043 |
| Gemini gemini-3.8-flash | 20 | 0.90 | 0.82 | 0.93 | 1.00 | $0.0315 | 32.6 | 2,701 |
| Routed (hybrid) | 20 | 0.91 | 0.81 | 0.95 | 1.00 | $0.0198 | 20.2 | 1,259 |

## Deployed latency

| Label | Question | Category | First event (s) | TTFT (s) | Total (s) | Retrieval (s) | LLM (s) | Cost |
|---|---|---|---|---|---|---|---|---|
| warm | rag-01 | rag | 4.0 | 13.2 | 21.3 | 6.5 | 14.3 | $0.0087 |
| warm | rag-04 | rag | 1.8 | 9.0 | 21.1 | 0.8 | 20.1 | $0.0197 |
| warm | rag-09 | rag | 3.6 | 9.1 | 18.4 | 0.6 | 17.2 | $0.0136 |
| warm | rag-12 | rag | 1.8 | 7.9 | 16.7 | 0.6 | 16.0 | $0.0123 |
| warm | rag-16 | rag | 2.2 | 7.8 | 14.1 | 0.9 | 13.1 | $0.0161 |
| warm | dat-01 | data | 1.7 | 6.5 | 9.9 | 0.1 | 9.7 | $0.0037 |
| warm | dat-03 | data | 3.1 | 12.1 | 15.9 | 0.0 | 15.7 | $0.0040 |
| warm | sum-01 | summary | 1.7 | 25.0 | 36.4 | 2.5 | 33.7 | $0.0336 |
| warm | web-01 | web | 2.1 | 43.7 | 70.1 | 17.2 | 52.6 | $0.0701 |
| warm | web-02 | web | 1.6 | 13.7 | 23.6 | 6.4 | 17.1 | $0.0175 |
| warm | cmp-01 | compare | 2.6 | 13.6 | 35.4 | 1.1 | 34.1 | $0.0427 |
| warm | cmp-05 | compare | 2.9 | 11.8 | 44.2 | 1.6 | 42.4 | $0.0503 |
| cold | rag-01 | rag | 54.0 | 65.1 | 73.5 | 8.3 | 15.4 | $0.0088 |
