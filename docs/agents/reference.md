# ChaosEngine agent reference

Version 1.20261126.0. Generator `945bf9656287`. Fetch on demand. Not always loaded.

One fact per row. The owner link is the normative file.

## Settings

| Key | Opt | Default | Flag or env | Source |
| --- | --- | --- | --- | --- |
| `source.repository` | value | `ShaftHQ/chaosengine-harness` | CHAOS_ENGINE_REPOSITORY | [owner](../../runtime/install_options.py#L119) |
| `source.ref` | value | `main` | --branch | [owner](../../runtime/install_options.py#L130) |
| `source.version` | value | `latest` | --version | [owner](../../runtime/install_options.py#L143) |
| `source.channel` | value | `main` | --channel | [owner](../../runtime/install_options.py#L156) |
| `network.offline` | opt-in | `false` | --offline | [owner](../../runtime/install_options.py#L170) |
| `network.bundle` | value | `` | --from-bundle | [owner](../../runtime/install_options.py#L185) |
| `network.ca_bundle` | value | `` | --ca-bundle | [owner](../../runtime/install_options.py#L199) |
| `network.use_gh_token` | opt-out | `true` | CHAOS_ENGINE_GH_AUTH | [owner](../../runtime/install_options.py#L213) |
| `install.scope` | value | `project` | --scope | [owner](../../runtime/install_options.py#L224) |
| `install.distribution` | value | `portable` | --distribution | [owner](../../runtime/install_options.py#L241) |
| `install.git_visibility` | value | `tracked` | --consumer, --tracked | [owner](../../runtime/install_options.py#L254) |
| `instructions.mode` | value | `merge` | --mode | [owner](../../runtime/install_options.py#L272) |
| `instructions.placement` | value | `top` | --instructions-placement | [owner](../../runtime/install_options.py#L290) |
| `hosts.enabled` | value | `[]` | --hosts | [owner](../../runtime/install_options.py#L304) |
| `hosts.infer` | opt-out | `true` | --no-infer-hosts | [owner](../../runtime/install_options.py#L319) |
| `hosts.portable_files` | value | `all` | --portable-hosts | [owner](../../runtime/install_options.py#L334) |
| `hosts.grok.lean_skills` | opt-in | `false` | --lean-grok-skills | [owner](../../runtime/install_options.py#L348) |
| `hosts.register_plugins` | opt-out | `true` | --no-register-plugins | [owner](../../runtime/install_options.py#L363) |
| `components.memory` | opt-out | `true` | --without-memory, --with-memory | [owner](../../runtime/install_options.py#L1) |
| `components.mempalace` | opt-out | `true` | --without-mempalace, --with-mempalace | [owner](../../runtime/install_options.py#L1) |
| `components.graphify` | opt-out | `true` | --without-graphify, --with-graphify | [owner](../../runtime/install_options.py#L1) |
| `components.ponytail` | opt-out | `true` | --without-ponytail, --with-ponytail | [owner](../../runtime/install_options.py#L1) |
| `components.caveman` | opt-out | `true` | --without-caveman, --with-caveman | [owner](../../runtime/install_options.py#L1) |
| `components.icm-architect` | opt-out | `true` | --without-icm-architect, --with-icm-architect | [owner](../../runtime/install_options.py#L1) |
| `addons.enabled` | value | `[]` | CHAOS_ENGINE_ADDONS | [owner](../../runtime/install_options.py#L379) |
| `addons.auto_detect` | opt-out | `true` | --no-auto-addons | [owner](../../runtime/install_options.py#L392) |
| `packs.shaft_skills_version` | value | `auto` | --shaft-skills-version | [owner](../../runtime/install_options.py#L407) |
| `packs.post_install` | opt-out | `true` | --skip-pack-post-install | [owner](../../runtime/install_options.py#L420) |
| `mcp.publish` | opt-in | `false` | --with-mcp, --without-mcp | [owner](../../runtime/install_options.py#L435) |
| `mcp.servers` | value | `[]` | --mcp-servers | [owner](../../runtime/install_options.py#L452) |
| `mcp.maven_tools.enabled` | opt-in | `false` | --with-maven-tools | [owner](../../runtime/install_options.py#L467) |
| `mcp.maven_tools.mode` | value | `native` | --maven-tools-mode | [owner](../../runtime/install_options.py#L482) |
| `provision.tools` | opt-out | `true` | --skip-tools | [owner](../../runtime/install_options.py#L496) |
| `provision.prerequisites` | value | `auto` | --skip-prerequisites | [owner](../../runtime/install_options.py#L511) |
| `paths.modify_user_path` | opt-out | `true` | --no-modify-path | [owner](../../runtime/install_options.py#L527) |
| `paths.bin_dir` | value | `` | --bin-dir | [owner](../../runtime/install_options.py#L542) |
| `paths.cache_dir` | value | `` | CHAOS_ENGINE_CACHE_DIR | [owner](../../runtime/install_options.py#L556) |
| `paths.data_dir` | value | `` | CHAOS_ENGINE_USER_DIR | [owner](../../runtime/install_options.py#L567) |
| `cache.max_mb` | value | `0` | CHAOS_ENGINE_CACHE_MAX_MB | [owner](../../runtime/install_options.py#L578) |
| `edits.policy` | value | `copy-aside` | --keep-edits | [owner](../../runtime/install_options.py#L589) |
| `backups.keep` | value | `20` | --backup-keep | [owner](../../runtime/install_options.py#L605) |
| `git_hooks.secret_guard` | opt-out | `true` | --no-secret-guard | [owner](../../runtime/install_options.py#L619) |
| `locks.project_wait_seconds` | value | `30` | CHAOS_ENGINE_LOCK_WAIT_SECONDS | [owner](../../runtime/install_options.py#L634) |
| `hooks.guard_wait_ms` | value | `60000` | CHAOS_ENGINE_GUARD_WAIT_MS | [owner](../../runtime/install_options.py#L645) |
| `stores.schedule` | opt-out | `true` | --no-store-schedule | [owner](../../runtime/install_options.py#L656) |
| `stores.schedule_at` | value | `03:15` | CHAOS_ENGINE_STORE_SCHEDULE_AT | [owner](../../runtime/install_options.py#L671) |
| `stores.refresh_on_session` | opt-out | `true` | CHAOS_ENGINE_STORE_REFRESH | [owner](../../runtime/install_options.py#L682) |
| `stores.stall_seconds` | value | `120` | CHAOS_ENGINE_STALL_SECONDS | [owner](../../runtime/install_options.py#L693) |
| `stores.graphify.extra_ignore` | value | `[]` |  | [owner](../../runtime/install_options.py#L704) |
| `stores.mempalace.mine` | value | `` | CHAOS_ENGINE_MEMPALACE_MINE | [owner](../../runtime/install_options.py#L714) |
| `stores.mempalace.full` | value | `` | CHAOS_ENGINE_MEMPALACE_FULL | [owner](../../runtime/install_options.py#L725) |
| `stores.mempalace.collection` | value | `` | CHAOS_ENGINE_MEMPALACE_COLLECTION | [owner](../../runtime/install_options.py#L736) |
| `session.resume_stale_days` | value | `7` | CHAOS_ENGINE_RESUME_STALE_DAYS | [owner](../../runtime/install_options.py#L747) |
| `ui.interactive` | opt-in | `false` | --interactive | [owner](../../runtime/install_options.py#L758) |
| `ui.verbosity` | value | `normal` | -q, --quiet, --verbose | [owner](../../runtime/install_options.py#L771) |
| `ui.color` | value | `auto` | --color | [owner](../../runtime/install_options.py#L787) |
| `ui.ascii` | opt-in | `false` | --ascii | [owner](../../runtime/install_options.py#L801) |
| `dry_run` | opt-in | `false` | -n, --dry-run | [owner](../../runtime/install_options.py#L815) |
| `yes` | opt-in | `false` | --yes, --no-input | [owner](../../runtime/install_options.py#L816) |
| `json` | opt-in | `false` | --json | [owner](../../runtime/install_options.py#L817) |
| `if_changed` | opt-in | `false` | --if-changed | [owner](../../runtime/install_options.py#L818) |
| `force` | opt-in | `false` | --force | [owner](../../runtime/install_options.py#L819) |
| `include_local` | opt-in | `false` | --include-local | [owner](../../runtime/install_options.py#L820) |
| `allow_dirty` | opt-in | `false` | --allow-dirty | [owner](../../runtime/install_options.py#L821) |
| `force_replace_source_tree` | opt-in | `false` | --force-replace-source-tree | [owner](../../runtime/install_options.py#L822) |
| `no_user_hooks` | opt-in | `false` | --no-user-hooks | [owner](../../runtime/install_options.py#L823) |
| `user_layer.hosts` | value | `[]` | --user-hosts | [owner](../../runtime/install_options.py#L824) |

## Environment

| Name | Class | Opt | Default | Effect | Source |
| --- | --- | --- | --- | --- | --- |
| `CE_ALLOW_BOX_LOCAL_AGENCY` | user | opt-in | `unset` | Set to 1 to allow the local-agency box pa… | [owner](../../skills/local-agency/scripts/require_rog_freetoken.py#L24) |
| `CE_HOOK_TRACE` | user | value | `unset` | unknown — see read site | [owner](../../hooks/launch.py#L396) |
| `CE_NEUTRAL_TERMS_FILE` | maint | value | `unset` | unknown — see read site | [owner](../../skills/job-apply/scripts/check_abstraction.py#L35) |
| `CE_OPENCODE_GUARD_TIMEOUT_MS` | user | value | `unset` | unknown — see read site | [owner](../../runtime/hook_surfaces.py#L210) |
| `CE_OPENCODE_PYTHON` | user | value | `unset` | unknown — see read site | [owner](../../runtime/hook_surfaces.py#L216) |
| `CE_OWNER_EMAIL` | user | value | `unset` | unknown — see read site | [owner](../../runtime/commit_identity.py#L188) |
| `CE_OWNER_IDENTITY` | user | value | `unset` | unknown — see read site | [owner](../../runtime/commit_identity.py#L184) |
| `CE_OWNER_NAME` | user | value | `unset` | unknown — see read site | [owner](../../runtime/commit_identity.py#L187) |
| `CE_ROG_CHECKOUT` | maint | value | `unset` | unknown — see read site | [owner](../../skills/local-agency/scripts/require_rog_freetoken.py#L23) |
| `CHAOS_AGENT_ID` | internal | value | `unset` | unknown — see read site | [owner](../../runtime/backups_watch.py#L33) |
| `CHAOS_BACKUPS_WATCH_PATH` | maint | value | `unset` | unknown — see read site | [owner](../../runtime/backups_watch.py#L242) |
| `CHAOS_BACKUP_WORKSPACES` | maint | value | `unset` | unknown — see read site | [owner](../../runtime/delete_guard.py#L5556) |
| `CHAOS_CHECKPOINTS_DIR` | maint | value | `unset` | unknown — see read site | [owner](../../runtime/progress_log.py#L25) |
| `CHAOS_DELETE_ACK` | maint | value | `unset` | unknown — see read site | [owner](../../runtime/delete_guard.py#L94) |
| `CHAOS_ENGINE_ADDON_PATHS` | user | value | `unset` | unknown — see read site | [owner](../../runtime/addon_catalog.py#L34) |
| `CHAOS_ENGINE_ALLOW_LINKED_WORKTREE` | user | value | `unset` | unknown — see read site | [owner](../../install.py#L8905) |
| `CHAOS_ENGINE_ALLOW_MISSING_EVAL` | user | opt-out | `unset` | Set to 1 to skip the eval-parity check. | [owner](../../runtime/silent_verify.py#L126) |
| `CHAOS_ENGINE_APPLY_UPDATE` | user | value | `unset` | unknown — see read site | [owner](../../hooks/lifecycle.py#L471) |
| `CHAOS_ENGINE_ARGV_ONLY` | internal | value | `unset` | unknown — see read site | [owner](../../bootstrap.py#L8060) |
| `CHAOS_ENGINE_BOOT_TIME` | internal | value | `unset` | unknown — see read site | [owner](../../runtime/task_ledger.py#L109) |
| `CHAOS_ENGINE_BRAND_SHOWN` | internal | value | `unset` | unknown — see read site | [owner](../../bootstrap.py#L2692) |
| `CHAOS_ENGINE_CLIENT_NAME_DENYLIST` | user | value | `unset` | unknown — see read site | [owner](../../bootstrap.py#L1058) |
| `CHAOS_ENGINE_CONFIG_HOME` | internal | value | `unset` | unknown — see read site | [owner](../../runtime/install_config.py#L95) |
| `CHAOS_ENGINE_CONSENT_PATH` | maint | value | `unset` | unknown — see read site | [owner](../../runtime/learning_session.py#L237) |
| `CHAOS_ENGINE_COPY_PROMPT` | internal | value | `unset` | unknown — see read site | [owner](../../bootstrap.py#L7520) |
| `CHAOS_ENGINE_DEBUG` | user | value | `unset` | unknown — see read site | [owner](../../bootstrap.py#L7669) |
| `CHAOS_ENGINE_DERIVED_VERSION` | internal | value | `unset` | unknown — see read site | [owner](../../bootstrap.py#L1672) |
| `CHAOS_ENGINE_DRAFT_SKILL_PRS` | user | opt-in | `unset` | Set to 1, with the CLI opt-in, to allow a… | [owner](../../runtime/draft_skill_pr.py#L28) |
| `CHAOS_ENGINE_DRY_RUN` | maint | value | `unset` | unknown — see read site | [owner](../../bootstrap.py#L5405) |
| `CHAOS_ENGINE_ENFORCE_RESEARCH_RECEIPT` | user | opt-in | `unset` | Set to a truthy value to require a resear… | [owner](../../hooks/guard.py#L3873) |
| `CHAOS_ENGINE_EVIDENCE_BRANCH` | maint | value | `unset` | unknown — see read site | [owner](../../runtime/mobile_retro.py#L65) |
| `CHAOS_ENGINE_EVIDENCE_BUILD_ID` | maint | value | `unset` | unknown — see read site | [owner](../../runtime/mobile_retro.py#L59) |
| `CHAOS_ENGINE_FILE_ISSUE` | user | value | `unset` | unknown — see read site | [owner](../../bootstrap.py#L1174) |
| `CHAOS_ENGINE_FIXTURE_ORIGIN` | internal | value | `unset` | unknown — see read site | [owner](../../bootstrap.py#L5134) |
| `CHAOS_ENGINE_FORCE` | maint | value | `unset` | unknown — see read site | [owner](../../bootstrap.py#L5404) |
| `CHAOS_ENGINE_GRAPHIFY_OUT` | maint | value | `unset` | unknown — see read site | [owner](../../hooks/retrieve_justification.py#L229) |
| `CHAOS_ENGINE_HOOK_EVENT` | internal | value | `unset` | unknown — see read site | [owner](../../hooks/launch.py#L66) |
| `CHAOS_ENGINE_HOOK_PAYLOAD` | internal | value | `unset` | unknown — see read site | [owner](../../hooks/launch.py#L23) |
| `CHAOS_ENGINE_HOOK_SOURCE` | internal | value | `unset` | unknown — see read site | [owner](../../runtime/hosts.py#L5526) |
| `CHAOS_ENGINE_HYPERLINKS` | user | value | `unset` | unknown — see read site | [owner](../../bootstrap.py#L845) |
| `CHAOS_ENGINE_INSTALL_URL` | maint | value | `unset` | unknown — see read site | [owner](../../install.sh#L105) |
| `CHAOS_ENGINE_JOB` | internal | value | `unset` | unknown — see read site | [owner](../../runtime/jobs.py#L44) |
| `CHAOS_ENGINE_JOBS_DIR` | maint | value | `unset` | unknown — see read site | [owner](../../runtime/jobs.py#L45) |
| `CHAOS_ENGINE_JOB_RUN` | internal | value | `unset` | unknown — see read site | [owner](../../runtime/jobs.py#L43) |
| `CHAOS_ENGINE_JSON` | user | value | `unset` | unknown — see read site | [owner](../../bootstrap.py#L790) |
| `CHAOS_ENGINE_LOCAL_CLONE` | maint | value | `unset` | unknown — see read site | [owner](../../bootstrap.py#L169) |
| `CHAOS_ENGINE_MEMPALACE` | maint | value | `unset` | unknown — see read site | [owner](../../runtime/hosts.py#L1043) |
| `CHAOS_ENGINE_NO_INPUT` | user | value | `unset` | unknown — see read site | [owner](../../bootstrap.py#L3535) |
| `CHAOS_ENGINE_OWNER_FINISH_GOAL` | user | value | `unset` | unknown — see read site | [owner](../../runtime/task_ledger.py#L101) |
| `CHAOS_ENGINE_PREREQ_DISK_PATH` | maint | value | `unset` | unknown — see read site | [owner](../../runtime/task_ledger.py#L692) |
| `CHAOS_ENGINE_PRIMARY` | maint | value | `unset` | unknown — see read site | [owner](../../runtime/delete_guard.py#L4617) |
| `CHAOS_ENGINE_PROTECTED_GROK_HOME` | internal | value | `unset` | unknown — see read site | [owner](../../runtime/grok_lean_config.py#L459) |
| `CHAOS_ENGINE_PROTECTED_GROK_HOME_LOG` | internal | value | `unset` | unknown — see read site | [owner](../../runtime/grok_lean_config.py#L472) |
| `CHAOS_ENGINE_PYTHON_PROBE_ONLY` | internal | value | `unset` | unknown — see read site | [owner](../../install.sh#L387) |
| `CHAOS_ENGINE_QUIET` | user | value | `unset` | unknown — see read site | [owner](../../bootstrap.py#L172) |
| `CHAOS_ENGINE_RELEASE_FEED` | user | value | `unset` | unknown — see read site | [owner](../../hooks/lifecycle.py#L434) |
| `CHAOS_ENGINE_RELEASE_VERSION` | user | value | `unset` | unknown — see read site | [owner](../../hooks/lifecycle.py#L435) |
| `CHAOS_ENGINE_RESOLVE_ONLY` | internal | value | `unset` | unknown — see read site | [owner](../../install.ps1#L540) |
| `CHAOS_ENGINE_RETRIEVE` | internal | value | `unset` | unknown — see read site | [owner](../../tool.py#L868) |
| `CHAOS_ENGINE_REVIEW_CAP_LIFT` | user | opt-in | `unset` | Owner lift of the two-review cap. | [owner](../../hooks/delegation_gate.py#L23) |
| `CHAOS_ENGINE_RUN_RECEIPT` | internal | value | `unset` | unknown — see read site | [owner](../../runtime/session_token_usage.py#L260) |
| `CHAOS_ENGINE_SESSION_ID` | internal | value | `unset` | unknown — see read site | [owner](../../hooks/retrieve_justification.py#L483) |
| `CHAOS_ENGINE_SESSION_WORKTREE` | internal | value | `unset` | unknown — see read site | [owner](../../runtime/session_logs.py#L19) |
| `CHAOS_ENGINE_SHAFT_FIXTURE_ORIGIN` | maint | value | `unset` | unknown — see read site | [owner](../../packs/shaft/sync.py#L55) |
| `CHAOS_ENGINE_SHIM_INTERPRETER` | maint | value | `unset` | unknown — see read site | [owner](../../install.ps1#L508) |
| `CHAOS_ENGINE_SIGNIFICANCE_CAPTURE` | user | opt-in | `unset` | Set to 1 to capture significance. | [owner](../../runtime/significance.py#L241) |
| `CHAOS_ENGINE_SPEC_DIR` | maint | value | `unset` | unknown — see read site | [owner](../../runtime/task_ledger.py#L847) |
| `CHAOS_ENGINE_STATE_DIR` | internal | value | `unset` | unknown — see read site | [owner](../../runtime/user_paths.py#L69) |
| `CHAOS_ENGINE_STORE_REGISTRY` | maint | value | `unset` | unknown — see read site | [owner](../../runtime/stores.py#L238) |
| `CHAOS_ENGINE_TASKS_DIR` | maint | value | `unset` | unknown — see read site | [owner](../../runtime/task_ledger.py#L116) |
| `CHAOS_ENGINE_TEST_REPO_GUARD` | internal | value | `unset` | unknown — see read site | [owner](../../runtime/stores.py#L2118) |
| `CHAOS_ENGINE_TOKEN_BUDGET` | user | value | `balanced` | Selects ultra-lean (alias lean), balanced… | [owner](../../hooks/lifecycle.py#L69) |
| `CHAOS_ENGINE_UPSTREAM_REPO` | user | value | `unset` | unknown — see read site | [owner](../../hooks/session_scratch.py#L254) |
| `CHAOS_ENGINE_USER_HOME` | internal | value | `unset` | unknown — see read site | [owner](../../runtime/user_paths.py#L29) |
| `CHAOS_ENGINE_USER_PATHS` | internal | value | `unset` | unknown — see read site | [owner](../../packs/java/installer.py#L453) |
| `CHAOS_ENGINE_USER_PAYLOAD` | internal | value | `unset` | unknown — see read site | [owner](../../hooks/launch.py#L527) |
| `CHAOS_ENGINE_VERBOSE` | user | value | `unset` | unknown — see read site | [owner](../../bootstrap.py#L218) |
| `CHAOS_ENGINE_WITHOUT` | user | opt-out | `unset` | Comma-separated component names to turn o… | [owner](../../runtime/install_config.py#L348) |
| `CHAOS_PROGRESS_LOG` | maint | value | `unset` | unknown — see read site | [owner](../../runtime/progress_log.py#L8) |
| `CHAOS_RADIO_SILENCE` | user | opt-in | `unset` | Blocks owner-visible status when set to 1… | [owner](../../runtime/radio_silence.py#L7) |
| `CHAOS_SESSION_CONTAINMENT_ROOTS` | internal | value | `unset` | unknown — see read site | [owner](../../runtime/delete_guard.py#L66) |
| `CHAOS_SESSION_CREATED_MANIFEST` | internal | value | `unset` | unknown — see read site | [owner](../../runtime/delete_guard.py#L63) |
| `CHAOS_SESSION_MANIFEST_HMAC` | internal | value | `unset` | unknown — see read site | [owner](../../runtime/delete_guard.py#L65) |
| `CHAOS_SESSION_WORKTREE` | internal | value | `unset` | unknown — see read site | [owner](../../hooks/retrieve_justification.py#L1701) |
| `CHAOS_YT_EXPECTED_AUTHORS` | maint | value | `unset` | unknown — see read site | [owner](../../runtime/delete_guard.py#L121) |
| `CHAOS_YT_VERIFIED_DELETE` | maint | value | `unset` | unknown — see read site | [owner](../../runtime/delete_guard.py#L114) |

## Keywords

| Phrase | Kind | Enforced by | Effect | Source |
| --- | --- | --- | --- | --- |
| `--allow-cloud` | owner-phrase | prose | Allows the OmniRoute cloud transport when the o… | [owner](../../references/execution-workflows.md#L1) |
| `babysit and merge it when green` | owner-phrase | prose | Selects the watch, fix, and confirm pull-reques… | [owner](../../references/work-github-playbook.md#L1) |
| `blocking: unverifiable` | status-token | prose | The only allowed stop while a required check is… | [owner](../../skills/chaos-engine/SKILL.md#check-and-deliver) |
| `CE_BRIEF_LOCATORS:` | brief-marker | code | Closing line that lists verbatim brief paths fo… | [owner](../../skills/local-agency/scripts/design_turn_gate.py#L11) |
| `ce_load: required` | brief-marker | code | A local worker brief must carry this line so th… | [owner](../../skills/local-agency/scripts/worker_ce_entry.py#L24) |
| `delegate` | owner-phrase | code | Selects a writer. The receipt is required befor… | [owner](../../hooks/delegation_gate.py#L1) |
| `delegate card` | brief-marker | prose | Short card a dispatched worker loads instead of… | [owner](../../references/delegate-card.md#L1) |
| `deliver` | owner-phrase | prose | Keep going until the in-scope work is merged or… | [owner](../../references/orchestrator-follow-through.md#L1) |
| `do not merge` | owner-phrase | code | Counts as out of scope from the owner, not insi… | [owner](../../hooks/guard.py#L209) |
| `Done` | status-token | prose | Say Done only after the pre-done self-review si… | [owner](../../skills/pre-done-self-review/SKILL.md#L1) |
| `HALT` | status-token | prose | Named stop that ends deliver or babysit. | [owner](../../references/orchestrator-follow-through.md#L1) |
| `ICM this` | owner-phrase | prose | Routes to the advisory ICM workspace architect. | [owner](../../runtime/harness_index.py#L161) |
| `Learning Session` | ritual | code | Required after every final delivery. | [owner](../../hooks/guard.py#L187) |
| `NEEDS-HUMAN` | status-token | prose | Human-only blocker routed to the orchestrator c… | [owner](../../references/sequential-wip.md#L1) |
| `normal mode` | owner-phrase | code | Turns off both companion cards for this session. | [owner](../../hooks/lifecycle.py#L229) |
| `ORCHESTRATOR + PARALLEL IMPLEMENTERS` | workflow | prose | Owner opt-in for file-disjoint units in isolate… | [owner](../../references/execution-workflows.md#L1) |
| `ORCHESTRATOR + SINGLE IMPLEMENTER` | workflow | prose | Default orchestrated mode. The orchestrator doe… | [owner](../../references/execution-workflows.md#L1) |
| `out of scope` | owner-phrase | code | Marks a named pull request out of scope for bab… | [owner](../../hooks/guard.py#L207) |
| `PDCA cap` | ritual | prose | At most three Plan-Do-Check-Act iterations. Rev… | [owner](../../references/delivery-cycle.md#L1) |
| `person-only attestation` | principle | prose | The agent will not sit an exam or feed live ans… | [owner](../../companions/ethics-card.md#L1) |
| `chaos-engine:agentic` | pr-marker | code | Marks an agentic pull request. Gates require a… | [owner](../../hooks/guard.py#L661) |
| `proceed unattended` | owner-phrase | prose | Enables adaptive follow-up by the process owner. | [owner](../../references/process-owner-scrum-master.md#L1) |
| `process-owner` | role | prose | Scrum-master only when asked. Product owner map… | [owner](../../references/roles.md#L1) |
| `radio silence` | mode | code | Blocks owner-visible status and routes status t… | [owner](../../runtime/radio_silence.py#L7) |
| `rung=free` | receipt-token | code | Delegation receipt fields checked by the gate. | [owner](../../hooks/delegation_gate.py#L1) |
| `retrieve: used` | receipt-token | code | Required record of the retrieve-first step. | [owner](../../hooks/guard.py#L1) |
| `review_cap` | receipt-token | code | Two adversarial reviews per subject unless an o… | [owner](../../hooks/delegation_gate.py#L23) |
| `implementer` | role | code | Implements one bounded specification before con… | [owner](../../hooks/kernel.py#L25) |
| `mechanical-helper` | role | code | Deterministic reversible spec-exact work. Stops… | [owner](../../hooks/kernel.py#L28) |
| `orchestrator` | role | code | Plans, synthesizes, and verifies. Does not impl… | [owner](../../hooks/kernel.py#L24) |
| `reviewer` | role | code | Independent read-only adversarial review. Never… | [owner](../../hooks/kernel.py#L26) |
| `tester` | role | code | Reproduces behavior and records regression evid… | [owner](../../hooks/kernel.py#L27) |
| `SOLO` | workflow | prose | One tightly coupled change. Record rung=direct. | [owner](../../references/execution-workflows.md#L1) |
| `explicit status request` | owner-phrase | prose | Forces a fresh poll of every registered agent. | [owner](../../references/delegation-cycle.md#L1) |
| `step back` | principle | prose | After two failed attempts, re-plan. Push back o… | [owner](../../identity.md#principles) |
| `stop caveman` | owner-phrase | code | Turns off the Caveman card for this session. | [owner](../../hooks/lifecycle.py#L232) |
| `stop ponytail` | owner-phrase | code | Turns off the Ponytail card for this session. | [owner](../../hooks/lifecycle.py#L234) |
| `supersede` | owner-phrase | prose | Open one replacing pull request per the kanban… | [owner](../../skills/kanban/SKILL.md#L1) |
| `tool.py entry` | owner-phrase | code | Hookless bots pass a stop phrase to entry to dr… | [owner](../../tool.py#L646) |
| `one file` | mode | code | Triage depth selects a plan size and a token-bu… | [owner](../../hooks/lifecycle.py#L38) |
| `work as orchestrator` | owner-phrase | prose | Selects orchestrated mode. With parallelize, se… | [owner](../../references/execution-workflows.md#L1) |

## Status codes

| Code | Meaning | Source |
| --- | --- | --- |
| `CE_CANCELLED` | unknown — see read site | [owner](../../hooks/kernel.py#L1421) |
| `CE_CONFIG_INVALID` | unknown — see read site | [owner](../configuration.md#L15) |
| `CE_CONFIG_REPLACE_FROM_FILE` | unknown — see read site | [owner](../configuration.md#L5) |
| `CE_CONFIG_SECRET` | unknown — see read site | [owner](../configuration.md#L5) |
| `CE_CORE_MISSING` | unknown — see read site | [owner](../../INSTALL.md#L1) |
| `CE_DELETE_GUARD` | unknown — see read site | [owner](../../runtime/instruction_mode.py#L1) |
| `CE_DEPENDENCY_RECEIPT_MISSING` | unknown — see read site | [owner](../../install.py#L9583) |
| `CE_DIAGNOSTIC_UNAVAILABLE` | unknown — see read site | [owner](../configuration.md#L1) |
| `CE_DUAL_GROK_HOOKS` | unknown — see read site | [owner](../../install.py#L1) |
| `CE_GROK_INSPECT_FAILED` | unknown — see read site | [owner](../../runtime/hosts.py#L1) |
| `CE_GROK_PROJECT_UNBOUND` | unknown — see read site | [owner](../../runtime/hosts.py#L1) |
| `CE_HOOKS_PROBE_FAILED` | unknown — see read site | [owner](../../install.py#L1) |
| `CE_HOSTS_RECEIPT_MISSING` | unknown — see read site | [owner](../../install.py#L1) |
| `CE_HOST_ADAPTER_DRIFT` | unknown — see read site | [owner](../../install.py#L1) |
| `CE_INVALID_RULESET` | unknown — see read site | [owner](../../hooks/kernel.py#L1) |
| `CE_INVALID_TRANSITION` | unknown — see read site | [owner](../../hooks/kernel.py#L1) |
| `CE_LIFECYCLE_STATE` | unknown — see read site | [owner](../../hooks/kernel.py#L1) |
| `CE_LIVESEO_WRITEOUT` | unknown — see read site | [owner](../../addons/design-skills/scripts/liveseo_gates.py#L1) |
| `CE_MANAGED_PYTHON_MISSING` | unknown — see read site | [owner](../../install.py#L1) |
| `CE_MEMORY_ORIGIN_MAIN_DESYNC` | unknown — see read site | [owner](../../runtime/hosts.py#L1) |
| `CE_MEMPALACE_UNINITIALIZED` | unknown — see read site | [owner](../../runtime/hosts.py#L1) |
| `CE_MODE_CONSUMER_CONFLICT` | unknown — see read site | [owner](../../runtime/instruction_mode.py#L1) |
| `CE_MODE_REPLACE_BACKUP` | unknown — see read site | [owner](../../runtime/instruction_mode.py#L1) |
| `CE_MODE_REPLACE_DIRTY` | unknown — see read site | [owner](../../runtime/instruction_mode.py#L1) |
| `CE_MODE_REPLACE_NEEDS_YES` | unknown — see read site | [owner](../../runtime/instruction_mode.py#L1) |
| `CE_MODE_REPLACE_SOURCE_TREE` | unknown — see read site | [owner](../../runtime/instruction_mode.py#L1) |
| `CE_MODE_REPLACE_UNSUPPORTED` | unknown — see read site | [owner](../../bootstrap.py#L1) |
| `CE_MODE_RESTORE_STAMP` | unknown — see read site | [owner](../../install.py#L1) |
| `CE_MODE_SCOPE_CONFLICT` | unknown — see read site | [owner](../../runtime/instruction_mode.py#L1) |
| `CE_OK` | unknown — see read site | [owner](../../hooks/kernel.py#L1) |
| `CE_OPENBOT_SKILL_MISSING` | unknown — see read site | [owner](../../install.py#L1) |
| `CE_RETRIEVE_DEGRADED` | unknown — see read site | [owner](../../runtime/overlay_match.py#L1) |
| `CE_SCOPE_USER_UNSUPPORTED` | unknown — see read site | [owner](../../bootstrap.py#L1) |
| `CE_SCOPE_USER_WROTE_PROJECT` | unknown — see read site | [owner](../../install.py#L1) |
| `CE_SESSION_MISSING_STOP` | unknown — see read site | [owner](../../hooks/kernel.py#L1658) |
| `CE_SESSION_REQUIRED` | unknown — see read site | [owner](../../hooks/kernel.py#L1) |
| `CE_STOP_COMPLETE` | unknown — see read site | [owner](../../hooks/kernel.py#L1658) |
| `CE_STOP_INCOMPLETE` | unknown — see read site | [owner](../../hooks/kernel.py#L1663) |
| `CE_TERMINAL_REPLAY` | unknown — see read site | [owner](../../hooks/kernel.py#L1) |
| `CE_TIMEOUT` | unknown — see read site | [owner](../../hooks/kernel.py#L1) |
| `CE_UNKNOWN_EVENT` | unknown — see read site | [owner](../../hooks/kernel.py#L1) |
| `CE_UNKNOWN_PHASE` | unknown — see read site | [owner](../../hooks/kernel.py#L1) |
| `CE_USER_CODEX_OVERRIDE` | unknown — see read site | [owner](../../runtime/user_layer.py#L1) |
| `CE_WIPED_RUNTIME` | unknown — see read site | [owner](../../install.py#L9583) |

## Commands

Subcommands below. Routes stay in the keywords glossary, which is generated from `runtime/harness_index.py`.

| Command | Source |
| --- | --- | --- |
| `install.py install` | [owner](../../install.py#L8922) |
| `install.py repair` | [owner](../../install.py#L8936) |
| `install.py addons` | [owner](../../install.py#L8979) |
| `install.py explain` | [owner](../../install.py#L8984) |
| `install.py bundle` | [owner](../../install.py#L8996) |
| `install.py cache` | [owner](../../install.py#L9000) |
| `install.py status` | [owner](../../install.py#L9002) |
| `install.py purge` | [owner](../../install.py#L9004) |
| `install.py init` | [owner](../../install.py#L9008) |
| `install.py upgrade` | [owner](../../install.py#L9028) |
| `install.py verify` | [owner](../../install.py#L9041) |
| `install.py restore-edits` | [owner](../../install.py#L9043) |
| `install.py config` | [owner](../../install.py#L9046) |
| `install.py show` | [owner](../../install.py#L9048) |
| `install.py path` | [owner](../../install.py#L9049) |
| `install.py validate` | [owner](../../install.py#L9050) |
| `install.py set` | [owner](../../install.py#L9051) |
| `install.py migrate-paths` | [owner](../../install.py#L9052) |
| `install.py restore` | [owner](../../install.py#L9068) |
| `install.py instructions` | [owner](../../install.py#L9074) |
