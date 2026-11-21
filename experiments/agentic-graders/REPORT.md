# Agentic graders on frozen #45 traces

Graders in `grade.py` score labelled fixtures with no vendor API key. They flag identical adjacent tool calls, a final answer that was required to cite a tool result and did not, and a web search chosen for a task that names a local file.

## Trace scan

`scan_transcripts` read `experiments/harness-ab/raw/*/*/transcript.md`.

| Measure | Value |
| --- | --- |
| Transcripts | 15 |
| Tool lines | 1032 |
| Adjacent heredoc stubs (`Execute: python3 - <<`) | 48 |
| Adjacent identical calls that are not that stub | 8 |
| Runs with a real identical streak of 3 or more | 1 (C/01, the same `Execute: CP=$(cat /tmp/shaft.cp)` line) |
| Uncited finals (claim of pass with no `mvn` or path citation) | 0 |

The heredoc lines are one-line headers. The transcript does not keep the script body, so those repeats are not evidence of the same call. One run in fifteen has a real identical-call streak. No final answer was uncited. That is not a material rate (threshold 20% of runs).

## Decision

No loop cap was added. The hypothesis did not hold on these traces. This was not a new live multi-run campaign.

The missing-citation and wrong-tool fixtures are constructed controls in the transcript's tool-line shape, because the frozen traces did not contain those failures. The identical-call fixture is the C/01 streak. The distinct-call fixture is the opening of A/01.
