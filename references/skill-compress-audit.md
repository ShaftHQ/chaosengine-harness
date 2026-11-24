# SkillOpt-style SKILL.md compression audit


Module: [`skill_compress_audit.py`](../runtime/skill_compress_audit.py).
Offline/script audit that **proposes** bounded compress actions for skill
bodies. **Never** auto-applies or auto-merges skill patches.

## Policy

| Do | Don't |
| --- | --- |
| Propose filler/bloat + refs-split hints | Write `SKILL.md` from the audit CLI |
| Gate future apply on eval-parity + unit tests | Weekly auto-mutate live skills |
| Keep L2 discipline (&lt;500 lines) measurable | Treat propose diffs as merged |

## CLI (zero-LLM)

```bash
python3 .chaos-engine/runtime/skill_compress_audit.py audit
python3 .chaos-engine/runtime/skill_compress_audit.py audit --skill self-improve --diff
python3 .chaos-engine/runtime/skill_compress_audit.py audit --strict   # exit 1 if over L2 budget
```

`--diff` embeds bounded unified-diff **stubs** in JSON only — files stay unchanged.

The same audit checks Agent Skills `name` and `description`: `name` is 1–64
characters, lowercase letters, digits, and single hyphens, and it equals the
parent directory. An indexed skill `description` is 60–220 characters, the
same band as the skill-index parity gate. The audit script's absolute ceiling
stays 1–1024 characters and does not replace that gate. Vendor and
plugin-adapter `SKILL.md` files are included; a short adapter is not exempt,
because it can still name the wrong directory. `permissions:` is unused
ChaosEngine-only metadata. The installer, the index, and this audit do not
read it. Do not add `allowed-tools`.

## Apply gate — opt-in draft PRs

Propose-only remains the default. Draft PRs are available **only** via
[`draft-skill-pr.md`](draft-skill-pr.md) / [`draft_skill_pr.py`](../runtime/draft_skill_pr.py):

1. Explicit `--opt-in` **and** `CHAOS_ENGINE_DRAFT_SKILL_PRS=1` (default OFF)
2. `python3 scripts/ci/chaos_engine_eval_parity.py` green (repo-only)
3. Focused unit tests green
4. `gh pr create --draft` only (`--execute`); **never** auto-merge; never apply without gate

```bash
python3 .chaos-engine/runtime/draft_skill_pr.py status
CHAOS_ENGINE_DRAFT_SKILL_PRS=1 python3 .chaos-engine/runtime/draft_skill_pr.py open --opt-in
```
