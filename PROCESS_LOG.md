# Process log — Veridex v2 (Assignment 2)

## AI tools used

Claude Code (Claude Opus 5.5) planned, implemented and tested most of the code under my
review; I made design decisions, ran the paid steps and signed every commit. At runtime:
OpenAI `gpt-6.1-sol` and `text-embedding-3-small`, Google `gemini-3.8-flash`, and
`gpt-6.1-sol` as the RAGAS judge.

## Development narrative

I extended Assignment 1 in five phase-sized branches: corpus, multi-agent core, streaming
UI, deployment, evaluation. What worked: one manifest driving the index, catalog and
license notice, and an inspectable router. What did not: GPT-6 rejects any temperature
except the default, which first broke every agent; an unanchored `.gcloudignore` pattern
silently dropped `src/veridex/data` from the Cloud Build upload; Tavily page extracts
pushed OpenAI calls past their timeout; and sequential searches made a web question take
176 s until the prompt asked for batched tool calls (70 s).

## Verification narrative

Beyond the 480+ offline tests, I ran real STDIO MCP servers with a Tavily stand-in, asked
live questions with all three keys, read the stored turns back from Firestore over REST,
rolled a new Cloud Run revision and confirmed a follow-up still resolved "the first paper
I asked about", and captured a cold start only after the instance-count metric showed
zero. A local ruff cache once hid an import-order failure that CI caught, so I now lint
with `--no-cache`.

## What I learned

The tools could not decide which papers were legally redistributable; I checked every
arXiv license. They also guessed model IDs and prices, so I verified IDs against each
provider's `/models` endpoint. Measured costs contradicted my assumption that Gemini is
always cheaper per query, which changed how I describe the routing trade-off.
