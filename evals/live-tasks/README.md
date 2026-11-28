# Live tasks

Offline tasks for a hidden verifier. At most a few tasks. No model and no network.
A check that does not run is skipped. A check that runs and is not measured is unknown.
Neither is a pass.

Each task directory holds `task.toml`, `instruction.md`, `environment/`, `tests/test.sh`,
and `solution/solve.sh`. Every authored file contains the same `canary: <guid>` line.
`tests/` is not in the agent workspace. It is copied in only after the handed-back tree
is cloned.

`runtime/live_task.py` rejects unknown keys, a missing file, a missing canary, and a
`max_steps` or timeout above the tier ceiling.

| difficulty | max_steps | agent timeout_sec | verifier timeout_sec |
| --- | --- | --- | --- |
| easy | 8 | 60 | 20 |
| medium | 20 | 180 | 30 |
| hard | 40 | 600 | 60 |

| task | why it is here |
| --- | --- |
| `001-refusal-offline` | Converts the golden-task `refusal-offline` check into a gradeable reward. |
| `002-stray-cr` | Closed #206: a shell script with a stray CR is a failed outcome. |
| `003-plain-rename` | Closed #237: a plain rename is a successful outcome, not a refused move. |

The oracle must score 1. The untouched environment must score 0. A missing, empty,
or non-numeric `reward.txt` is `verifier-error`, not 0.
