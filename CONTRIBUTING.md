# Contributing

ChaosEngine is a harness for testers, frontend and backend developers, product owners, and scrum masters. It is independent of team, language, framework, and product. The license is MIT, copyright ChaosEngine contributors (`LICENSE`).

Read [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) before you participate. Report vulnerabilities through [SECURITY.md](SECURITY.md), not through an issue.

## Discuss, then open a pull request

Open an issue first for a bug, a behavior change, a spec, a story, or a test plan. Use the forms in `.github/ISSUE_TEMPLATE/`. Blank issues are disabled.

Open a pull request when the change is ready for review, and link the issue. A small wording or example fix can start as a pull request when no issue exists.

## Non-code work

Specs, user stories, test plans, and documentation are welcome. You can contribute them without writing code. Use the non-code work form. Say who the work is for and how a reviewer can tell it is done.

## Review floor

Every change needs at least one independent adversarial review. The author is not that reviewer. The reviewer tries to refute the change.

Request two independent adversarial reviews when the change is any of these:

- a public contract (behavior other people or tools rely on)
- an irreversible change
- an outbound action (sending, publishing, or acting outside this repository)

Say in the pull request whether you requested one review or two.

This floor is for pull requests to this repository. The two-review step in the [overview](guides/overview.md#what-it-does) delivery loop describes how ChaosEngine itself runs work in an adopting project; it is not this repository's merge rule.

## Local checks

`install.py` requires Python 3.11 or newer. Java and Maven are not required.

Check the syntax of each Python file you edit:

```bash
python3 -m py_compile path/to/file.py
```

On Windows, use `py -3` anywhere this file says `python3`.

Doctor is `install.py doctor`. It is not a `tool.py` subcommand. `python3 tool.py --help` lists entry, retrieve, stores, job, checkpoint, maintain, and related tools. It does not list `doctor` and it accepts no doctor flags.

From this source tree:

```bash
python3 install.py doctor --project .
```

In a project where ChaosEngine is already installed:

```bash
python3 .chaos-engine/install.py doctor --project .
```

`doctor` accepts `--project`, `--json`, `--agent-summary`, `--digest`, and `--fix-next-only`. `--json` cannot be combined with `--agent-summary`. `--json` cannot be combined with `--fix-next-only`.

`python3 tool.py maintain` fast-forwards, reinstalls, runs doctor, refreshes stores, and reloads. Run it only when you want that full sequence.

## Tests

The offline suite is in `tests/`. It needs `pytest`, `pyyaml` and, for parallel runs, `pytest-xdist`:

```bash
python3 -m pytest -q -n auto tests
```

The suite points `HOME`-level host config (for example `GROK_HOME`) at throwaway folders, so it does not touch your real settings. CI (`.github/workflows/ci.yml`) runs it on every pull request, with the structure, syntax and Markdown link checks.

## Roadmap

[ROADMAP.md](ROADMAP.md) is generated from epic ShaftHQ/SHAFT_ENGINE#8056. Do not edit it by hand. Change the epic, then run `python3 .github/scripts/roadmap.py`. A weekly job fails when the file no longer matches the epic.

## Outside skills

Outside skills are not accepted yet. The supply-chain policy is tracked in ShaftHQ/SHAFT_ENGINE#8060 and is not in this tree. Do not add a second policy here.

## Install

The commands that work today are the ones in [INSTALL.md](INSTALL.md). They still download:

- `https://raw.githubusercontent.com/ShaftHQ/chaosengine-harness/main/install.sh`
- `https://raw.githubusercontent.com/ShaftHQ/chaosengine-harness/main/install.ps1`

Do not publish a different installer URL until INSTALL.md does.

The PyPI and npm packages named `chaosengine-harness` are reserved for the planned weekly-release channel. Today they are `0.0.1` placeholders and do not install this harness. The one-liner in the README is the latest-from-`main` channel.
