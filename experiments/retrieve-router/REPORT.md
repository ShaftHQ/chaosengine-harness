# Retrieve router eval

Label: fixture backends, not live stores. P7 (the #45 model rig) was not run. No live Graphify or MemPalace process was scored. The router under test is `runtime/retrieve.py`. The frozen set is `experiments/retrieve-router/questions.json` (26 questions). Sixty honest gold questions were not available without inventing lines, so this is the largest set whose `path:line` was checked against the file on disk.

`experiments/retrieve-router/score.py` wrote `experiments/retrieve-router/last-score.json`. Figures below are that file, not a hand estimate.

## Arms (recall@5)

| Arm | recall@5 |
| --- | --- |
| no-retrieve | 0.0 |
| router (fixture backends) | 0.23076923076923078 |
| oracle | 1.0 |

Share of the no-retrieve → oracle gap closed: 0.23076923076923078. That is `(0.23076923076923078 - 0.0) / (1.0 - 0.0)`.

Implicit-clue slice (15 questions; a rare question token, from `corpus_split.rare_tokens` after punctuation is split off, does not occur in the gold path or line): recall@5 0.13333333333333333.

Overall minus implicit: 9.743589743589745 points. The K2 rule opens a semantic-weighting follow-up only at 15 points or more. This run does not. K2: no gap under that rule. Implicit recall is still lower than overall recall.

Routing accuracy against the table labels on this set: 1.0 (26/26). The labels were written to the same first-match table the classifier implements. This is agreement with those labels, not a second human labeling.

## Scale (K3)

Synthetic padded MemPalace and Memory bodies at N=8, 4N=32, and 16N=128 items. Bytes are the receipt `bytes` field. They stay at 800, inside the 800-byte cap, and do not grow with N.

| Store | N bytes | 4N bytes | 16N bytes | N p95 s | 4N p95 s | 16N p95 s |
| --- | --- | --- | --- | --- | --- | --- |
| memory | 800 | 800 | 800 | 0.006755687994882464 | 0.006942359003005549 | 0.007177873980253935 |
| mempalace | 800 | 800 | 800 | 0.03402915201149881 | 0.032923097984166816 | 0.03487272097845562 |

p95 is the in-process timer around `retrieve()`, 21 samples. Latency is not required to be flat.

## Router notes

- Graphify exit 3 re-queries once with the top `id:` candidate. Exit 4 and an empty result are misses. A degraded result, including a backend mismatch, does not fall back.
- At most two backends. A second store runs only on a miss. Two hit lists merge with reciprocal rank fusion, then cap at 8 hits and 800 bytes. Hits are `{path, line, store, score, route}`. A hit whose path is not a file under the project is dropped.
- `route.reason` is on the receipt. `deja` was already absent from `STORES`; it was left absent.
- `--budget`, `--depth`, `--wing`, and `--results` are passed when the route has a value and, for `--wing`, when `mempalace.yaml` names one wing. `--query-task` is not passed.
- No project-local MemPalace knowledge graph. No write-back.
