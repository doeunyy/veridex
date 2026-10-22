## RAGAS (routed)

| Category | n | Faithfulness | Answer relevancy | Context precision | Context recall |
|---|---|---|---|---|---|
| Corpus RAG | 20 | 0.93 | 0.82 | 0.94 | 1.00 |
| Summary | 3 | 0.89 | 0.66 | 0.97 | 1.00 |
| Data (SQL) | 4 | 0.94 | 0.80 | 1.00 | 1.00 |
| Web | 3 | 0.62 | 0.73 | – | – |
| **All** | 30 | **0.90** | **0.79** | **0.95** | **1.00** |

## Routing decisions (routed run)

| Agent | Rule | Provider | Calls (decisions) | Fallbacks |
|---|---|---|---|---|
| data | `structured_lookup` | gemini | 4 | 0 |
| research | `multi_step_synthesis` | openai | 3 | 0 |
| research | `single_lookup` | gemini | 20 | 0 |
| summary | `long_context` | gemini | 3 | 0 |
| supervisor | `classify` | gemini | 60 | 0 |

## Cost and latency (in-process runs)

| Run | Questions | Mean cost / query | Total cost | Median total (s) | Median TTFT (s) | Median retrieval (s) | Median LLM (s) |
|---|---|---|---|---|---|---|---|
| routed | 30 | $0.0313 | $0.94 | 32.4 | 19.1 | 1.3 | 30.2 |
| openai | 20 | $0.0444 | $0.89 | 28.7 | 16.0 | 1.0 | 27.8 |
| gemini | 20 | $0.0315 | $0.63 | 32.6 | 18.4 | 1.1 | 31.3 |

## Provider comparison (corpus RAG questions)

| Provider (all agents) | RAG questions | Faithfulness | Answer relevancy | Context precision | Context recall | Mean cost / query | Median total (s) | Output tokens / query |
|---|---|---|---|---|---|---|---|---|
| OpenAI gpt-6.1-sol | 20 | 0.97 | 0.85 | 0.94 | 1.00 | $0.0444 | 28.7 | 1,043 |
| Gemini gemini-3.8-flash | 20 | 0.90 | 0.82 | 0.93 | 1.00 | $0.0315 | 32.6 | 2,701 |
| Routed (hybrid) | 20 | 0.93 | 0.82 | 0.94 | 1.00 | $0.0329 | 32.8 | 2,544 |

## Deployed latency

| Label | Question | Category | First event (s) | TTFT (s) | Total (s) | Retrieval (s) | LLM (s) | Cost |
|---|---|---|---|---|---|---|---|---|
| warm | rag-01 | rag | 6.0 | 25.3 | 41.5 | 7.2 | 33.8 | $0.0370 |
| warm | rag-04 | rag | 3.6 | 24.5 | 40.1 | 1.1 | 38.7 | $0.0355 |
| warm | rag-09 | rag | 3.4 | 22.7 | 37.1 | 1.1 | 35.8 | $0.0318 |
| warm | rag-12 | rag | 2.7 | 20.4 | 36.1 | 1.3 | 34.6 | $0.0321 |
| warm | rag-16 | rag | 3.7 | 16.0 | 22.5 | 0.9 | 21.3 | $0.0193 |
| warm | dat-01 | data | 2.6 | 7.6 | 11.0 | 0.1 | 10.7 | $0.0052 |
| warm | dat-03 | data | 2.8 | 10.2 | 14.5 | 0.1 | 14.4 | $0.0076 |
| warm | sum-01 | summary | 3.2 | 17.5 | 34.5 | 3.2 | 31.1 | $0.0399 |
| warm | web-01 | web | 3.2 | 57.3 | 77.3 | 15.2 | 62.0 | $0.0668 |
| warm | web-02 | web | 4.8 | 40.0 | 58.8 | 4.1 | 54.5 | $0.0270 |
| cold | rag-01 | rag | 44.8 | 69.0 | 86.6 | 6.7 | 40.0 | $0.0303 |
| cold | dat-01 | data | 43.8 | 50.0 | 53.5 | 0.1 | 14.8 | $0.0048 |
