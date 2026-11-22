# Harness A/B/C report

Issue #45. Fifteen measured Grok CLI runs on one machine, interleaved A1 B1 C1 A2 B2 C2 A3 B3 C3 A4 B4 C4 A5 B5 C5. Arms: A bare project, B generic `AGENTS.md`, C ChaosEngine installed from the pinned one-liner with `--hosts grok`.

This is a loss for the ChaosEngine arm on the frozen total. Mean total (correctness + quality, out of 100): B 52.9000, A 50.2000, C 20.2000. Arm C did not lose the Maven correctness heuristic. Its quality scores are the frozen 120000-character bundle, which for every C run is the install tree and not the test project.

## Freeze

| Item | Value |
| --- | --- |
| Rubric commit | `d6c8da70bd95f319ca5e5b553f361b2b0f2f853b` |
| Turn-cap note | `4bf52810f79868521d40fdedeab4f4854cdbb396` (`DEVIATIONS.md`) |
| Harness pin for arm C | `a74873e53754f130ae0841459b0229575a4d6c14` |
| Client | grok 1.0.85 (d15ff2d24f6f) [alpha] |
| Model flag | `--model grok-4.7` |
| Recorded usage key | `grok-4.7-build` on every run |
| Host | <user>@<host> |
| Maven cache | warm, shared `~/.m2` |
| Stop reason | `end_turn` on all 15 runs |

`procedure.md` still says `--max-turns 40`. Measured runs used 400, recorded before the campaign in `DEVIATIONS.md`. No run hit 400 turns (maximum was 104). No run hit the 45-minute cap. The rubric, prompt, fixture, price table, and 120000-character bundle cap were not changed after the runs.

`score.py --grade` wrote both grader totals for every run. The process then printed argparse usage because `--grade` was missing from the help-only guard. That print is not a grade failure. The guard now includes `--grade`. `score.py --self-check` prints `self-check ok`.

## Headline numbers

`score.py --summary` after `--write-results`:

| Arm | Correctness mean | Quality mean | Total mean | Tokens mean | Seconds mean | Estimated USD mean |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A | 15.0000 | 35.2000 | 50.2000 | 5487412.6000 | 598.2000 | 6.6231 |
| B | 15.0000 | 37.9000 | 52.9000 | 4272225.2000 | 526.4000 | 5.1399 |
| C | 19.8000 | 0.4000 | 20.2000 | 3502815.2000 | 654.8000 | 4.5638 |

Medians for total: A 50.0000, B 52.5000, C 16.0000. Ranges for total: A 49.0000–52.0000, B 46.0000–60.5000, C 15.0000–27.0000.

Quality per 100k tokens, mean (median): A 1.0582 (1.0856), B 1.7782 (1.0274), C 0.0388 (0.0000).

Quality per minute, mean (median): A 5.0805 (5.7568), B 5.7083 (5.6881), C 0.0800 (0.0000).

CLI `total_cost_usd` stored as `meter_cost_usd`, summed across five runs: A 17.455124, B 14.060816, C 11.827632. All fifteen runs: 43.343572. The price-table estimate is higher (A 33.115372, B 25.699600, C 22.819080, all runs 81.634052). The estimate was not written over the meter.

Charts were not drawn. `charts/MISSING.txt` says matplotlib is not installed. The procedure writes that file when the import fails.

## Per run

Every run: Grok exit 0, `timed_out` false, questions 0, three Maven exits 0, Surefire run 1 has two passing tests except A05 and B03 which have three. Build is 10 and determinism is 5 on every run. Login is 0 and negative is 0 on every run: the frozen rules require `standard_user`, or `locked_out_user` / `wrong` plus `password`, inside a run-1 passing test method body. Checkout is 12 only when that body also contains `checkout` and a complete-page marker.

| Run | Correctness | Quality (g1, g2) | Total | Tokens | Seconds | Meter USD | Turns | Tools |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A01 | 15 | 37.0 (36, 38) | 52.0 | 1845541 | 233 | 1.365826 | 21 | 44 |
| A02 | 15 | 34.5 (34, 35) | 49.5 | 10454983 | 1108 | 6.928968 | 80 | 125 |
| A03 | 15 | 35.5 (34, 37) | 50.5 | 2354531 | 370 | 1.836562 | 25 | 63 |
| A04 | 15 | 34.0 (34, 34) | 49.0 | 3132030 | 339 | 1.896592 | 31 | 50 |
| A05 | 15 | 35.0 (33, 37) | 50.0 | 9649978 | 941 | 5.427176 | 76 | 105 |
| B01 | 15 | 45.5 (47, 44) | 60.5 | 2156935 | 323 | 1.455734 | 30 | 51 |
| B02 | 15 | 34.5 (36, 33) | 49.5 | 3357986 | 517 | 2.058180 | 31 | 51 |
| B03 | 15 | 37.5 (35, 40) | 52.5 | 11845997 | 1175 | 7.326454 | 104 | 179 |
| B04 | 15 | 41.0 (40, 42) | 56.0 | 925678 | 290 | 0.748528 | 13 | 25 |
| B05 | 15 | 31.0 (31, 31) | 46.0 | 3074530 | 327 | 2.471920 | 25 | 47 |
| C01 | 15 | 0.0 (0, 0) | 15.0 | 3271207 | 472 | 1.962202 | 39 | 61 |
| C02 | 27 | 0.0 (0, 0) | 27.0 | 4050333 | 1041 | 3.190154 | 25 | 56 |
| C03 | 15 | 1.0 (1, 1) | 16.0 | 7845997 | 1168 | 5.039462 | 63 | 97 |
| C04 | 27 | 0.0 (0, 0) | 27.0 | 1794836 | 421 | 1.214572 | 21 | 45 |
| C05 | 15 | 1.0 (1, 1) | 16.0 | 551703 | 172 | 0.421242 | 13 | 33 |

C02 and C04 are the only runs whose correctness is above the build-plus-determinism floor of 15, and that is the checkout string rule (12), not a higher build. C03 and C05 stay at correctness 15. Their totals are 16 because quality is 1. That point is both graders awarding hygiene 1 for a harness skills README inside the truncated install, with every other quality item 0.

## Grader disagreement

No quality item differs by more than 20% of that item's maximum. Both graders returned a parseable total on every run. None were omitted.

## Why arm C quality is near zero

The frozen bundler walks `sorted(project.rglob("*"))`, keeps `.java`, `.xml`, `.properties`, `.md`, `.json`, and `.txt`, skips `.chaos-engine`, `.grok`, `.git`, and `target`, and stops at 120000 characters. It does not skip `.agents/` or `.memory/`.

Each C project on disk has a `pom.xml` and one Java test (107–115 suffix-matched files outside the stripped directories). Each C grader prompt lists 29 files, all under dot-directories, zero Java files, and zero `pom.xml`. The prompts start at `.agents/plugins/marketplace.json` and end in `.memory/schema/` with a `# TRUNCATED` marker, at about 116000 characters. Both graders were told to score only evidence in that source and to give 0 when evidence is missing. They did.

Fourteen of the fifteen prompts end with `# TRUNCATED`. B04 does not: it includes `pom.xml` and its only Java file, `src/test/java/testPackage/SauceDemoTest.java`. The other A and B prompts are truncated. Java files on disk are 1–10 per run. Java files inside those prompts are 0 except B01, which includes one. Several A/B prompts do include `pom.xml`. Those graders still found TestNG, properties, and POM evidence in the prefix they were shown and scored the mid-30s to mid-40s (B01 45.5, B05 31.0).

The published quality numbers are those grader means. They were not recomputed with a larger cap, a different walk order, or a second prompt. Correctness does not use the bundle. It uses `pom.xml`, Surefire XML, and the Java method bodies on disk.

## Artifacts

- `results.csv` from `score.py --write-results`
- `charts/MISSING.txt`
- `raw/<arm>/<NN>/` meta, transcripts, Maven logs, Surefire XML, and grader prompts
- `raw/blind-map.json` (the blinded trees themselves are gitignored)
- Project archives larger than the portable source cap (2 MiB per file) are not in this tree. The scored evidence is `results.csv` and `raw/`.

## Result

On the frozen total, generic `AGENTS.md` (B) is ahead of bare (A), and both are ahead of ChaosEngine (C). Arm C used fewer tokens and less metered money, took similar or longer wall time, and its Maven runs were green. The composite loss is the quality channel, measured on a bundle that never contained the C test sources.
