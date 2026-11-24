# SHAFT pack routing

Version-pinned upstream skills from ShaftHQ/SHAFT_ENGINE (`shaft-skills/`). The add-on receipt tag is the pin. Do not float `main`.

ChaosEngine keeps the coverage matrix, schema conformance, security checks, and review gates. The pack owns framework client and assertion syntax.

## Concern to specialist

| ChaosEngine domain | Upstream skill |
| --- | --- |
| Entry | `shaft-developer` |
| API | `shaft-api-testing` |
| Assertions | `shaft-assertions` |
| Database | `shaft-database-testing` |
| Test Data | `shaft-test-data-design` |
| Execution / Grid / Cloud | `shaft-test-execution` |
| Locators | `shaft-locator-design` |
| Non-Functional / Security | `shaft-nonfunctional-test-design` |

Specialist skills are siblings of `shaft-developer` under the root below.

## Where to open the router

| Project | Action |
| --- | --- |
| Core checkout (`kind` `core`) | Open `shaft-skills/shaft-developer/SKILL.md`. |
| User project, add-on installed | Open `.chaos-engine/addons/shaft-engine-users/shaft-developer/SKILL.md`. |
| User project, add-on missing | Stop and print the install flag `--with-shaft-engine-users` (or rerun the installer). Do not invent SHAFT client syntax. |
| Denied (`--without-shaft-engine-users`) | Native tooling. Do not load the pack. |

`route(pack_kind, addon_present, denied)` returns `pack`, `blocked`, or `native` for the same cases: installed add-on, missing add-on, and denied or `none`.

## Detector limits

The detector is read-only. It does not run Maven or Gradle.

- POM walk: root POM plus module POMs through depth 3, at most 50 files. Depth 4 is not read.
- Gradle: root `build.gradle`, root `build.gradle.kts`, and `gradle/libs.versions.toml` only. Nested Gradle files are not read.

## OpenAPI 3.1

OpenAPI 3.1 conformance stays on Schemathesis even in SHAFT repos when Draft-7 JSON Schema validation is insufficient.
