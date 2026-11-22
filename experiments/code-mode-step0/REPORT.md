# Code mode step 0

Decision: **keep**.

The drop rule is: drop if chained turns are under 20% of turns, or if intermediate tool results are under 25% of uncached input. Neither observed figure is under its line. This does not change an installer default. P7 and the Codex campaign were not run. No security advisory was read.

## What was measured

Existing host sessions on this machine, not the #45 `experiments/harness-ab/raw/*/meta.json` files. Those metas store `tool_calls` as an integer and a session usage total. They do not store per-result sizes, so they cannot answer this question. Ordinary sessions do store result bodies.

`runtime/learn_traces.py` now stamps `resultBytes` on each tool result at collect time and keeps `toolResultBytes` on the session. The figures below were scored from bodies and usage already on disk (`measure_tool_result_pressure`), not from a fresh collect of those sessions.

Hosts in the token and pipe figures: Claude (`input_tokens` on the assistant message, which is the uncached portion) and Codex (`last_token_usage.input_tokens` minus `cached_input_tokens`). A turn counts as intermediate when the new user content is only tool results (Claude) or a tool output is still pending (Codex). The whole uncached request is attributed, so this share is an upper bound on tokens that are the tool body itself, not a tokenizer slice. Grok is not in the percentage: `usage.json` is per user turn, and a per-result token share would be invented.

| Figure | Value |
| --- | --- |
| Files read | 1501 |
| Claude+Codex model turns | 366 |
| Pipe turns (one tool result in, one tool call out, no assistant text) | 179 |
| Pipe share | 0.4890710382513661 (179/366) |
| Uncached tokens | 11970461 |
| Uncached tokens on intermediate tool-result turns | 11527048 |
| Intermediate share | 0.9629577340421559 (11527048/11970461) |
| Claude+Codex tool results | 279 |
| Claude+Codex tool-result bytes | 986533 |
| Grok tool results | 53189 |
| Grok tool-result bytes | 157556026 |
| Grok share of uncached input | not measured |

Pipe share is above 20%. The request-level intermediate share is above 25%. The drop rule does not fire.

Grok's 157,556,026 result bytes are real and are not converted into a percent of uncached tokens.
