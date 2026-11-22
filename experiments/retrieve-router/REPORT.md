# Retrieve router eval

Label: fixture backends, not live stores. P7 (the #45 model rig) was not run. No live Graphify or MemPalace process was scored. `retrieve_py` is `retrieve(query, store=pick_store(query))`. `router_v2` is `classify_scope` through `retrieve(query)` with no store. No second router was added.

Frozen set: `experiments/retrieve-router/questions.json` (60 questions, sha256 `4c90c7e18e2a2033e7d8cecf5437bfa6c9024311d4738c3deeb5f94f72a5fbc1`). The scorer does not rewrite that file.

## K1

| Arm | recall@5 | gap closed |
| --- | --- | --- |
| no-retrieve | 0.0 | |
| retrieve_py | 0.21666666666666667 | 0.21666666666666667 |
| router_v2 | 0.26666666666666666 | 0.26666666666666666 |
| oracle | 1.0 | |

Gap closed is `(arm - no-retrieve) / (oracle - no-retrieve)`.

## K2

Implicit-clue slice: 38 questions whose `question_rare_tokens` list is empty. recall@5 is reported separately. A follow-up is required only when that slice is at least 15 points below the arm's overall recall@5.

| Arm | implicit recall@5 | points below overall | follow-up |
| --- | --- | --- | --- |
| retrieve_py | 0.13157894736842105 | 8.508771929824563 | False |
| router_v2 | 0.21052631578947367 | 5.614035087719299 | False |

router_v2 routing accuracy against the frozen labels: 1.0. The labels were written to the same first-match table the classifier implements. This is agreement with those labels, not a second human labeling.

## K3

Synthetic padded MemPalace and Memory bodies at N=8, 4N=32, and 16N=128. Bytes are the receipt `bytes` field. They stay inside the 800-byte cap and do not grow with N.

| Arm | Store | N bytes | 4N bytes | 16N bytes | N p95 s | 4N p95 s | 16N p95 s |
| --- | --- | --- | --- | --- | --- | --- | --- |
| retrieve_py | memory | 800 | 800 | 800 | 0.004932873998768628 | 0.004720775003079325 | 0.004505118995439261 |
| retrieve_py | mempalace | 800 | 800 | 800 | 0.007203422981547192 | 0.008118085999740288 | 0.008037934981985018 |
| router_v2 | memory | 800 | 800 | 800 | 0.005619478004518896 | 0.005564313993090764 | 0.005882254015887156 |
| router_v2 | mempalace | 800 | 800 | 800 | 0.009258756006602198 | 0.008856908971210942 | 0.009598083997843787 |

p95 is the in-process timer around `retrieve()`, 21 samples. Latency is not required to be flat.
