# ChaosEngine Single-Line Installer Revamp Research and Agent Specification

The ShaftHQ/chaosengine-harness single-line installer provisions the portable harness reliably (01:22 total runtime in the captured installation, concluding with 18/18 healthy doctor components), yet its terminal user experience suffers from triple-printed headers, low-contrast ANSI blue labels (standard Tango blue \#3465A4 measures 2.23:1 against a \#303030 GNOME Dark background), leaked dependency stdout (git, gh, node), stale scrollback status lines, and a 43-line post-install text dump that breaks URLs mid-scheme<sup>1</sup>. Cross-platform research across Astral uv, Anthropic Claude Code, mise, and terminal UI standards points to a unified upgrade: a zero-dependency Python standard-library ANSI/VT100 UI module shared by bootstrap.py and install.py that renders a proportional half-block brand mark, an in-place collapsing 6-step checklist, a terse completion summary, and a redacted failure-recovery panel combining a one-click OSC 8 GitHub issue link with an AI self-healing prompt<sup>3</sup>.

Two evidence constraints directly govern how an implementing AI agent should execute this specification. First, raw fetches of assets/brand/lockup-light.svg, bootstrap.py, install.sh, and shafthq.github.io/docs/agentic/chaos-engine were inaccessible during retrieval, even though the repository file inventory confirms their canonical locations<sup>1</sup>; consequently, the agent must inspect assets/brand/lockup-light.svg and the installer Python/shell files inside the local checkout rather than extrapolating exact SVG paths or hex colors. Second, no universal terminal standard binds a hyperlink click directly to copying multi-line text to the clipboard—OSC 8 opens URIs (https:, file:) while OSC 52 pushes text to the clipboard on emission—so failure recovery pairs automatic best-effort clipboard injection (or an OS-native copy tool plus a saved prompt file) with a borderless, selection-safe prompt block<sup>7</sup>.

This single Markdown document provides both the empirical UX audit and cross-OS benchmark findings (Part I) and the agent-optimized technical specification (Part II). Prior ChaosEngine governance rules—including freezing always-loaded-budget.json, maintaining one shared installer backend, preserving foreign host registrations, and gating outbound GitHub actions behind explicit user confirmation—apply as binding invariants, whereas rendering mechanics, clipboard defaults, and host presentation carry explicit challenge questions encouraging the implementing agent to push back with cleaner solutions<sup>13</sup>.

## Part I: Baseline UX Audit and Cross-Platform Research

### Audit of Captured Installer Screenshots

Examining both captured Linux terminal screenshots (<user>@<host> inside /media/mohab/Data/chaosengine-harness) shows that install.sh, bootstrap.py, and install.py each print uncoordinated headers and summaries across the same run. Because of the resulting vertical sprawl, even a maximized 1080p terminal window cannot display both the initial banner and the final Next: checklist without scrolling.

| **UX Defect Category** | **Observed Evidence in Screenshots** | **User Experience Impact** |
|----|----|----|
| Pre-banner forwarding noise | install.sh prints three plain lines (ChaosEngine moved to..., Installing ChaosEngine into..., Download: ...bootstrap.py) above the banner | Exposes raw forwarding plumbing before the brand mark and immediately duplicates target paths<sup>1</sup> |
| Mismatched logo stroke weight | Left C mixes a thick solid spine, thin horizontal strokes, corner ticks, and one red block; right Ǝ uses hairline ─┐/─┤/─┘ lines | Faint hairline Ǝ reads like a broken table border rather than a balanced CƎ / ChaosEngine emblem |
| Triple-printed metadata | Project prints under the logo, repeats with Source, then prints a third time alongside Commit, Doctor, and Hosts | Wastes vertical height and reveals uncoordinated handoffs between bootstrap.py and install.py |
| Redundant trace and stale status | Trace (last 4 of 26) repeats PASS lines already shown in \[✓\] steps, followed by a frozen Status 6/6 · Elapsed 01:21 line reading provisioning tools | Leaves contradictory in-progress text permanently in scrollback after all six steps have succeeded |
| Low-contrast ANSI blue labels | Standard ANSI blue renders Status, Project, Source, Guide, Receipt, and To get started: against a dark gray background | Degrades legibility on dark terminal themes and obscures primary section anchors<sup>2</sup> |
| Broken URL wrapping and jargon | Codex guidance wraps mid-scheme (http / s://developers.openai.com/codex/hooks) alongside internal terms (Caveman + Ponytail, file/hook) | Breaks terminal auto-link detection and crowds onboarding with internal harness terminology |
| Leaked raw dependency stdout | Three bare words (git, gh, node) print on separate lines directly above Next: | Indicates uncaptured subprocess or probe output bleeding directly into user-facing stdout |
| Counterproductive Next: order | Step 2 after successful install tells a first-time user to run python3 .chaos-engine/install.py uninstall --project . | Surfaces destructive teardown ahead of verification or first-session usage and exposes long script paths<sup>13</sup> |

### Quantitative Color Contrast and Terminal Readability Analysis

Standard ANSI dark blue (\033\[34m) is notoriously unreadable on dark developer terminals. Computing WCAG relative luminance contrast ratios across common dark terminal backgrounds—GNOME Terminal Dark (#303030), VS Code Integrated Terminal (#1E1E1E), and Windows Terminal Campbell (#0C0C0C)—alongside a light terminal (#FFFFFF) quantifies the legibility gap and exposes an important dark/light inversion pitfall<sup>2</sup>.

| **Palette Candidate** | **Representative Hex** | **GNOME Dark (#303030)** | **VS Code Dark (#1E1E1E)** | **Windows Terminal (#0C0C0C)** | **Light Background (#FFFFFF)** | **Guidance** |
|----|----|----|----|----|----|----|
| Classic ANSI Blue | \#0000AA | 1.01:1 (Fail) | 1.25:1 (Fail) | 1.47:1 (Fail) | 13.29:1 (AAA) | Prohibited for text<sup>2</sup> |
| Tango Blue (34m) | \#3465A4 | 2.23:1 (Fail) | 2.81:1 (Fail) | 3.30:1 (Fail) | 5.93:1 (AA) | Remove all \033\[34m labels<sup>2</sup> |
| Standard Cyan (36m) | \#06989A | 3.75:1 (Large only) | 4.74:1 (AA) | 5.56:1 (AA) | 3.52:1 (Large only) | Acceptable for rules/icons<sup>2</sup> |
| Coral Red Accent | \#F43F5E | 3.59:1 (Large only) | 4.54:1 (AA) | 5.33:1 (AA) | 3.67:1 (Large only) | Brand spark and failure mark<sup>2</sup> |
| Bright Blue (94m) | \#729FCF | 4.76:1 (AA) | 6.01:1 (AA) | 7.06:1 (AA) | 2.77:1 (Fail) | Dark-mode-only blue<sup>2</sup> |
| Muted Gray | \#9CA3AF | 5.20:1 (AA) | 6.57:1 (AA) | 7.70:1 (AA) | 2.54:1 (Fail) | Prefer SGR dim (2m)<sup>2</sup> |
| Sky 256 (39) | \#00AFFF | 5.39:1 (AA) | 6.81:1 (AA) | 7.99:1 (AA) | 2.45:1 (Fail) | High-visibility dark accent<sup>2</sup> |
| Bright Cyan (96m) | \#34E2E2 | 8.25:1 (AAA) | 10.42:1 (AAA) | 12.22:1 (AAA) | 1.60:1 (Fail) | Primary dark-theme accent<sup>2</sup> |
| Soft White | \#E5E7EB | 10.66:1 (AAA) | 13.47:1 (AAA) | 15.80:1 (AAA) | 1.24:1 (Fail) | Never hardcode on unknown BG<sup>2</sup> |

Hardcoding bright RGB colors such as \#E5E7EB (1.24:1) or \#34E2E2 (1.60:1) solves dark-mode contrast while breaking light-mode terminals (#FFFFFF)<sup>2</sup>. Therefore, primary values and body prose should always inherit the terminal's **default foreground**, secondary captions should use **SGR dim (\033\[2m)** so polarity adapts automatically, and accents should rely on terminal-themed ANSI colors (cyan, green, yellow, red) while stripping all color codes when NO_COLOR is set<sup>2</sup>.

### Cross-OS One-Line Installer Benchmark

Evaluating how modern cross-platform developer tools design their single-line installers identifies clear conventions for unattended execution, shell ergonomics, and concise output. Retrieved documentation provided direct commands and observed terminal output for Astral uv and Anthropic Claude Code, plus installation channel guidance for mise; verbatim terminal transcripts for bun and rustup were not present in accessible sources during this research pass, so the design guidelines below synthesize strictly from verified tool documentation and observed outputs.

| **Benchmark Dimension** | **Astral uv** | **Anthropic Claude Code** | **mise** | **Target ChaosEngine Behavior** |
|----|----|----|----|----|
| Unix / macOS / WSL entry | curl -LsSf https://astral.sh/uv/install.sh \| sh plus wget -qO- fallback<sup>4</sup> | curl -fsSL https://claude.ai/install.sh \| bash with channel/pin args (stable, 2.1.89)<sup>3</sup> | Install script recommended on macOS plus brew install mise<sup>5</sup> | POSIX sh compatible (curl -fsSL ... \| sh + wget fallback) with version pins<sup>1</sup> |
| Windows PowerShell entry | powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 \| iex"<sup>4</sup> | irm https://claude.ai/install.ps1 \| iex plus native .cmd script option<sup>3</sup> | Multi-channel native installs | Default -ExecutionPolicy ByPass PowerShell wrapper plus short irm \| iex and .cmd note<sup>1</sup> |
| Piped stdin and configuration | Unattended by default; uses UV_INSTALL_DIR and UV_NO_MODIFY_PATH=1 env vars<sup>22</sup> | Community setup guides note curl \| bash consumes stdin, requiring bash \<(curl ...) for prompts<sup>23</sup> | Non-blocking script execution | Never read stdin during piped install; mirror flags via CHAOSENGINE\_\* env vars<sup>22</sup> |
| Terminal footprint on success | Prints 5 clean lines ending in everything's installed!<sup>24</sup> | Minimal install output followed by claude --version and claude doctor<sup>3</sup> | Clean step confirmation | Collapse sub-details on step pass; limit post-install summary to under 20 lines |
| Post-install recovery and PATH | Prints exact source ~/.local/bin/env and restart instructions<sup>20</sup> | Distinguishes native Windows vs WSL2 and verifies via claude doctor<sup>3</sup> | Standard PATH activation | Run doctor inline during verification; show only actionable host gaps |

Two operational lessons carry directly into ChaosEngine. First, uniform CHAOSENGINE\_\* environment variables work identically across POSIX sh, Windows PowerShell (\$env:...), and CI pipelines, eliminating fragile -s -- quoting errors<sup>22</sup>. Second, separating unattended installation (curl ... \| sh / irm ... \| iex) from any future guided role/tool wizard (chaosengine init planned via pipx install chaosengine-harness in issue \#8058) keeps the one-liner fast and deadlock-free while reserving interactive configuration for a packaged CLI<sup>13</sup>.

### Terminal UI Libraries, Hyperlinks, Clipboard, and GitHub Issue Limits

ChaosEngine's single-line installer promises zero pre-installed Python requirements by downloading bootstrap.py and provisioning managed runtimes (uv, Python 3.11.x, and Node 24.19.0 / 26.x) inside .chaos-engine-runtime-generations/<sup>1</sup>. That bootstrap sequence creates an architectural boundary: importing third-party PyPI TUI libraries (rich, yaspin, textual) during Stage-1 bootstrap would fail on clean machines or offline bundles<sup>1</sup>.

| **UI Implementation Option** | **Pre-Runtime Availability** | **Windows Compatibility** | **Features & Complexity Trade-Off** | **Recommendation** |
|----|----|----|----|----|
| Python stdlib ANSI/VT100 module (ce_ui.py) | Zero dependencies; works immediately in bootstrap.py, install.py, and air-gapped bundles<sup>1</sup> | Requires ctypes SetConsoleMode (ENABLE_VIRTUAL_TERMINAL_PROCESSING) because CPython leaves VT100 disabled by default<sup>6</sup> | Full control over OSC 8, OSC 52, NO_COLOR, WT_SESSION, and minimal startup overhead<sup>8</sup> | Primary renderer for all one-liner stages and install.py<sup>13</sup> |
| rich (Console, Status, Live) | Requires external wheel; unavailable before managed Python/venv provisioning | Native legacy_windows handling and VT detection<sup>26</sup> | Built-in NO_COLOR/FORCE_COLOR/TTY_COMPATIBLE, spinners, and OSC 8 hyperlinks<sup>7</sup> | Optional Tier-1 layer only inside future packaged pipx CLI (#8058), if justified<sup>13</sup> |
| Compiled Go/Rust binary (bubbletea / ratatui) | Self-contained binary | Native Windows Console API | Requires cross-compiled release binaries and duplicates Python installer logic | Reject; conflicts with \#8058 single-backend invariant<sup>13</sup> |

For one-click GitHub bug submission on failure, OSC 8 escape sequences (\033\]8;id=\<id\>;\<uri\>\033\\\<text\>\033\]8;;\033\\, with \007 BEL as an alternative terminator for multiplexer compatibility) embed clickable URLs inside modern terminals<sup>7</sup>. Primary community tracking in Alhadis/OSC8-Adoption and product documentation confirms OSC 8 support in Windows Terminal (\>= v1.4.3141.0, detectable via WT_SESSION), iTerm2 (\>= 3.1), GNOME Terminal (\>= 3.26 / VTE \>= 0.50), GNOME Console (46.0), Ptyxis (47.6), Ghostty, Kitty (\>= v0.19), WezTerm, Alacritty (\>= v0.11), VS Code (\>= v1.72), Zellij (\>= v0.21.0), and tmux (\>= v3.4 with terminal-features "\*:hyperlinks"), while ConEmu lacks support<sup>7</sup>. An AI-assisted reference (vtdn.dev, which notes it has not completed independent human verification) additionally lists legacy xterm, PuTTY, rxvt-unicode, st, and GNU Screen as unsupported for OSC 8 while listing iTerm2, Kitty, Ghostty, WezTerm, Alacritty, and Windows Terminal for OSC 52 clipboard writes<sup>8</sup>. Importantly, an outdated Windows check once broke OSC 8 inside Claude Code until WT_SESSION detection was fixed, underscoring that ChaosEngine must explicitly inspect WT_SESSION on Windows<sup>25</sup>.

GitHub Issue Forms (.github/ISSUE_TEMPLATE/\*.yml) automatically bind URL query parameters to any input field carrying an alphanumeric/underscore id<sup>29</sup>. However, official GitHub documentation warns that exceeding server URL limits triggers a **414 URI Too Long error** without publishing an exact byte ceiling<sup>31</sup>. Because URL percent-encoding expands structured Markdown installer failure snippets by **1.49x** (312 raw characters become 466 URI characters)<sup>2</sup>, pre-filled URLs must stay under a defensive cap (recommended \<= 4,500 total encoded characters, roughly 2,700 raw characters of prioritized telemetry). Whenever full diagnostics exceed that budget, the installer should write a sanitized local file for manual attachment; notably, GitHub's issue form attachment specification accepts .txt, .log, and .json files (up to 25 MB) whereas .md is not in the supported upload list<sup>30</sup>, making .txt or .log essential for drag-and-drop issue attachments.

## Part II: AI-Agent-Optimized Revamp Requirements Specification

### Target Architecture and Agent Agency Charter

| **Specification Element** | **Repository Grounding and Scope** |
|----|----|
| Target Repository | ShaftHQ/chaosengine-harness (MIT license; root VERSION 0.4.20261115.5)<sup>1</sup> |
| Existing Files in Scope | install.sh, install.ps1, bootstrap.py, install.py, hosts.py, dependencies.py, client_name_scrub.py<sup>1</sup> |
| Assets to Inspect Locally | assets/brand/lockup-light.svg (canonical header lockup referenced in README.md) and any sibling assets/brand/\* files<sup>1</sup> |
| New Files Recommended | Shared stdlib UI helper (ce_ui.py or in-tree module), .github/ISSUE_TEMPLATE/install-failure.yml<sup>29</sup> |
| Binding System Invariants | Do not raise always-loaded-budget.json; keep one backend (bootstrap.py/install.py/hosts.py); preserve foreign registrations in .codex/config.toml and ~/.grok/config.toml; keep portable profile default; never execute outbound GitHub writes without explicit user consent<sup>13</sup> |

**Agent Agency and Pushback Charter:** Requirements tagged \[INVARIANT\] represent hard compatibility, security, or cross-OS boundaries. Requirements tagged \[DESIGN\] represent strongly recommended defaults derived from the UX audit and benchmark research—**you have explicit authority to challenge, simplify, or propose superior alternatives for any \[DESIGN\] item** once you inspect bootstrap.py, install.py, and assets/brand/lockup-light.svg in the live repository. Document any proposed deviation with concrete evidence and trade-offs before applying breaking changes to CLI flags, exit codes, or output snapshots.

### Requirement 1: Entrypoint Normalization and Unattended Execution Contract

| **Req ID** | **Tag** | **Requirement Specification** |
|----|----|----|
| REQ-ENTRY-01 | \[INVARIANT\] | Keep ShaftHQ/SHAFT_ENGINE forwarding intact while defaulting public one-liners to ShaftHQ/chaosengine-harness across POSIX sh (curl -fsSL ... \| sh with wget -qO- fallback), PowerShell (powershell -ExecutionPolicy ByPass -c "irm ... \| iex"), and Windows CMD<sup>1</sup> |
| REQ-ENTRY-02 | \[INVARIANT\] | Never block on stdin during piped execution; run 100% unattended by default and require both an explicit --interactive flag and an openable /dev/tty before prompting<sup>23</sup> |
| REQ-ENTRY-03 | \[DESIGN\] | Mirror CLI options via identical CHAOSENGINE\_\* environment variables (CHAOSENGINE_VERSION, CHAOSENGINE_PROJECT, CHAOSENGINE_QUIET, CHAOSENGINE_VERBOSE, CHAOSENGINE_NO_CLIPBOARD, CHAOSENGINE_JSON) across sh and PowerShell<sup>22</sup> |
| REQ-ENTRY-04 | \[INVARIANT\] | Suppress pre-banner forwarding/download stdout lines once bootstrap.py can paint the header (unless --verbose or a Stage-0 failure occurs), and capture all subprocess probe output so stray tokens (git, gh, node) never leak to stdout |
| REQ-ENTRY-05 | \[DESIGN\] | Select output profile automatically from TTY, CI, and flag state while guaranteeing non-zero exit status whenever doctor fails (exit != 0 or status == Blocked)<sup>15</sup> |

| **Runtime Condition** | **Selected Mode** | **In-Place Cursor Rewrites** | **Color and Hyperlink Behavior** |
|----|----|----|----|
| stdout.isatty() and not CI and TERM != dumb | Interactive TTY | Enabled (must restore cursor \033\[?25h in try/finally and SIGINT/SIGTERM handlers) | Auto-detected ANSI + OSC 8 (WT_SESSION included)<sup>8</sup> |
| Piped stdout, CI=true, GITHUB_ACTIONS=true, or TERM=dumb | Append-Only Log | Disabled (single milestone line per step) | Disabled unless FORCE_COLOR set (overridden by NO_COLOR)<sup>18</sup> |
| --json | Machine JSON | Disabled (valid JSON on stdout only) | Disabled<sup>15</sup> |
| --quiet | Terse | Disabled (final pass/fail line only) | Follows NO_COLOR / TTY |

### Requirement 2: Rendering Engine and Color Contrast Architecture

| **Req ID** | **Tag** | **Requirement Specification** |
|----|----|----|
| REQ-UI-01 | \[INVARIANT\] | Implement UI primitives using Python standard library modules only (sys, os, shutil, ctypes, time, urllib.parse, base64), imported identically by bootstrap.py and install.py without external PyPI dependencies<sup>1</sup> |
| REQ-UI-02 | \[INVARIANT\] | On Windows (os.name == "nt"), enable ENABLE_VIRTUAL_TERMINAL_PROCESSING (0x0004) via ctypes GetStdHandle(-11) / SetConsoleMode, falling back gracefully to plain text if VT activation fails on legacy consoles<sup>6</sup> |
| REQ-UI-03 | \[INVARIANT\] | Eliminate all \033\[34m (dark blue) styling; render primary data in terminal default foreground, labels in SGR dim (\033\[2m), status accents in theme-safe ANSI (36m/96m on confirmed dark, 32m, 33m, 31m), and honor NO_COLOR over FORCE_COLOR<sup>2</sup> |
| REQ-UI-04 | \[DESIGN\] | Adapt layout to shutil.get_terminal_size((80, 24)): side-by-side logo + metadata at \>= 84 columns, stacked header at 60–83 columns, compact single-line header below 60 columns; never split URLs mid-scheme across lines |

### Requirement 3: Faithful Product Logo Alignment

| **Req ID** | **Tag** | **Requirement Specification** |
|----|----|----|
| REQ-LOGO-01 | \[INVARIANT\] | Inspect assets/brand/lockup-light.svg (and any sibling SVGs in assets/brand/) inside the local checkout to extract true aspect ratio, glyph silhouettes, and brand palette before finalizing banner strings<sup>1</sup> |
| REQ-LOGO-02 | \[DESIGN\] | Render the C + Ǝ (or canonical SVG emblem) using Unicode half-blocks (▀, ▄, █, ▌, ▐) and quadrants (▛, ▜, ▙, ▟) so both glyphs share uniform bold stroke weight and clean visual alignment |
| REQ-LOGO-03 | \[DESIGN\] | Provide three degradation tiers: UTF-8 truecolor/256-color half-blocks matching SVG colors, UTF-8 16-color semantic ANSI, and ASCII/TERM=dumb single-line \[ChaosEngine \<version\>\] fallback |

Illustrative half-block header prototype for terminals \>= 84 columns wide (adjust pixel cells and exact color escapes after reading assets/brand/lockup-light.svg locally):

█▀▀▀ ▀▀▀█ ChaosEngine 0.4.20261115.5

█ ■ ▄▄▄█ Project /media/mohab/Data/chaosengine-harness

█▄▄▄ ▄▄▄█ Source ShaftHQ/chaosengine-harness@main (22ded966)

Illustrative narrow-terminal (\< 60 columns) and TERM=dumb single-line header fallback:

\[ChaosEngine 0.4.20261115.5\] ShaftHQ/chaosengine-harness@main (22ded966)

### Requirement 4: Uncluttered Checklist, Bounded Details, and Target Output Examples

| **Req ID** | **Tag** | **Requirement Specification** |
|----|----|----|
| REQ-UX-01 | \[INVARIANT\] | Render Project, Source, and resolved Commit once in the top header card (updating Commit in-place after Step 1) rather than repeating metadata across bootstrap, install, and receipt sections |
| REQ-UX-02 | \[DESIGN\] | Show a bounded 1–2 line indented sub-detail rail (└─ ...) strictly beneath the currently active \[⠋\] step during TTY execution, then erase/collapse it when the step turns \[✓\]; suppress raw trace tails and Status blocks on successful runs |
| REQ-UX-03 | \[DESIGN\] | Compress the post-install summary to \<= 18 lines: one readiness line with doctor ratio, one compact host status summary, actionable remediation lines only when a host requires user action (such as Codex /hooks trust), clickable log/guide links, and positive Next steps |

Target successful interactive TTY installation (\>= 84 columns; note that while Step 4 runs, └─ Checking ctx7 --version... appears transiently beneath line 4 and collapses once Step 4 completes):

█▀▀▀ ▀▀▀█ ChaosEngine 0.4.20261115.5

█ ■ ▄▄▄█ Project ~/Data/chaosengine-harness

█▄▄▄ ▄▄▄█ Source ShaftHQ/chaosengine-harness@main (22ded966)

\[✓\] Resolve source 00:01

\[✓\] Download source 00:33

\[✓\] Install core 00:05

\[✓\] Provision dependencies 00:23

\[✓\] Verify installation 00:05

\[✓\] Activate clients 00:04

✓ Installed cleanly in 01:22 · Doctor healthy (18/18 components)

Hosts claude (active) · grok (active) · copilot (IDE) · codex (needs /hooks trust)

Action Codex: run /hooks once to trust .codex/hooks.json (↗ docs)

Trace .chaos-engine-state/install-trace.json (↗ open)

Next

1\. Open Claude Code or Grok in this project and invoke /chaos-engine

2\. Run python3 .chaos-engine/install.py doctor --project . anytime to verify

Target unattended CI / non-TTY installation (CI=true, redirected stdout, or TERM=dumb):

ChaosEngine 0.4.20261115.5 \| ShaftHQ/chaosengine-harness@main (22ded966)

Project: /workspace/repo

\[1/6\] Resolve source ... ok (0.9s)

\[2/6\] Download source ... ok (33.1s)

\[3/6\] Install core ... ok (4.8s)

\[4/6\] Provision dependencies ... ok (23.2s)

\[5/6\] Verify installation ... ok (5.0s)

\[6/6\] Activate clients ... ok (4.1s)

Result: PASS (01:22) \| Doctor: 18/18 healthy \| Hosts: claude, codex(needs-trust), grok

### Requirement 5: One-Click Failure Reporting and Deterministic Redaction

| **Req ID** | **Tag** | **Requirement Specification** |
|----|----|----|
| REQ-ERR-01 | \[INVARIANT\] | Apply deterministic secret/PII redaction (extending client_name_scrub.py<sup>1</sup>) before writing files, terminal summaries, or URLs: mask home usernames (/home/\<USER\>, /Users/\<USER\>, C:\Users\\USER\>), hostnames, user:pass@ URLs, token prefixes (ghp\_, gho\_, github_pat\_, sk-, xai-, AIza, AKIA), and \*\_TOKEN/\*\_KEY/\*\_SECRET/\*\_PASSWORD env vars<sup>16</sup> |
| REQ-ERR-02 | \[INVARIANT\] | Collect only non-sensitive environment telemetry: OS name/version/kernel, CPU arch, WSL vs native Windows status, active shell, Python/Node/uv versions, ChaosEngine VERSION + 40-hex commit, sanitized flags, failing step/exit code, doctor --json code, and last 15 redacted trace lines |
| REQ-ERR-03 | \[INVARIANT\] | Create .github/ISSUE_TEMPLATE/install-failure.yml with explicit id fields<sup>29</sup> and encode the issues/new?template=install-failure.yml URL under a hard \<= 4,500-character encoded cap (accounting for ~1.49x URL expansion) to avoid GitHub 414 URI Too Long responses<sup>2</sup>; write full sanitized logs to .chaos-engine-state/failure-report.txt (.txt matches GitHub's 25 MB upload allowlist<sup>30</sup>) |
| REQ-ERR-04 | \[DESIGN\] | Detect OSC 8 support (WT_SESSION, iTerm.app, VTE_VERSION \>= 5000, KITTY_WINDOW_ID, GHOSTTY_RESOURCES_DIR, WEZTERM_EXECUTABLE, TERM_PROGRAM=vscode, or tmux \>= 3.4)<sup>7</sup> and emit a single clickable anchor; on unsupported terminals, display only the short base template URL, attachment path (.chaos-engine-state/failure-report.txt), and a gh issue create --body-file one-liner if gh is installed |

Proposed .github/ISSUE_TEMPLATE/install-failure.yml schema using query-bindable element IDs (version_commit, os_env, failing_step, diagnostics):

> YAML
>
> name: Installer Failure Report\
> description: Report a ChaosEngine single-line installer or doctor failure\
> title: "\[Installer\] Failure at step: "\
> labels: \["bug", "installer"\]\
> body:\
> - type: input\
> id: version_commit\
> attributes:\
> label: ChaosEngine Version / Commit\
> - type: input\
> id: os_env\
> attributes:\
> label: OS, Shell, and Runtime Versions\
> - type: input\
> id: failing_step\
> attributes:\
> label: Failing Step and Exit Code\
> - type: textarea\
> id: diagnostics\
> attributes:\
> label: Sanitized Trace Tail and Doctor JSON\
> description: Attach .chaos-engine-state/failure-report.txt for full redacted logs.

Target failure output example on an interactive TTY (rendered with top/bottom rules only—zero left/right │ box pipes—so drag-selection of the AI prompt copies clean Markdown):

\[✓\] Resolve source 00:01

\[✓\] Download source 00:12

\[✓\] Install core 00:04

\[✗\] Provision dependencies 00:09 (exit 1)

└─ Command failed: ctx7 --version (ETIMEDOUT 104.16.x.x:443)

\[ \] Verify installation

\[ \] Activate clients

✗ Installation failed at step 4/6: Provision dependencies

1.  Report upstream (1-click): \[↗ Open pre-filled GitHub Issue\]\
    Full sanitized report: .chaos-engine-state/failure-report.txt

2.  Fix locally with your AI agent (✓ copied to clipboard · file: agent-prompt.md):\
    ──────────────────────────────────────────────────────────────────────────────\
    ChaosEngine install failed at step 4/6 (Provision dependencies, exit 1).\
    Env: Linux 6.8 x86_64 \| bash 5.2 \| Python 3.12.3 \| ChaosEngine 22ded966\
    Error: ETIMEDOUT running managed ctx7 --version\
    Files: .chaos-engine-state/failure-report.txt, .chaos-engine-state/install-trace.json

Inspect failure-report.txt and run python3 .chaos-engine/install.py doctor --project . --json

to diagnose the root cause. Apply the minimal local fix or workaround and verify

doctor passes cleanly. Do NOT open a GitHub issue, push branches, or submit an

upstream PR to ShaftHQ/chaosengine-harness without asking my explicit permission first.

──────────────────────────────────────────────────────────────────────────────

### Requirement 6: Clipboard Transfer and AI Self-Healing Prompt

| **Req ID** | **Tag** | **Requirement Specification** |
|----|----|----|
| REQ-AI-01 | \[DESIGN\] | On failure in a local interactive TTY (unless CI=true or --no-clipboard / CHAOSENGINE_NO_CLIPBOARD=1), attempt clipboard copy via native tools (pbcopy, wl-copy, xclip -selection clipboard, xsel --clipboard, clip.exe / Set-Clipboard) followed by OSC 52 fallback (\033\]52;c;\<base64\>\033\\) for remote SSH/tmux sessions<sup>8</sup>; always write the identical text to .chaos-engine-state/agent-prompt.md and emit an OSC 8 file:// link where supported |
| REQ-AI-02 | \[INVARIANT\] | Render the terminal prompt block with horizontal separator rules only (no vertical │ box walls and minimal leading indentation) so manual drag-selection or triple-clicking copies intact Markdown |
| REQ-AI-03 | \[INVARIANT\] | Embed an explicit permission stop-gate inside the generated prompt instructing the user's AI agent to debug, patch locally, and verify doctor before asking the user whether to open or update an upstream issue or PR<sup>14</sup> |

### Acceptance Verification Matrix

| **Check ID** | **Test Harness** | **Pass Criterion** |
|----|----|----|
| AC-01 | Output snapshot (TTY, CI, --json) | Single header metadata block; zero leaked subprocess stdout (git/gh/node); non-zero exit when doctor blocks<sup>15</sup> |
| AC-02 | ANSI & NO_COLOR lint | Zero occurrences of \033\[34m; NO_COLOR=1 strips all color SGR codes while retaining bold/dim attributes<sup>2</sup> |
| AC-03 | Width breakpoints (50, 80, 120 cols) | Zero clipped boxes, zero wrapped URLs mid-scheme, clean narrow single-line banner |
| AC-04 | Secret redaction fuzz suite | Synthetic ghp\_, sk-, Bearer, user:pass@, and /home/\<USER\>/ strings are 100% absent from failure-report.txt, agent-prompt.md, and issue URLs<sup>1</sup> |
| AC-05 | GitHub 414 length boundary | Given a 50 KB synthetic trace, the generated pre-filled URL stays strictly \<= 4,500 encoded bytes<sup>2</sup> |
| AC-06 | Cross-OS shell & Windows VT | sh -n POSIX check passes on install.sh; Windows SetConsoleMode handles both modern Windows Terminal and legacy conhost fallback<sup>4</sup> |
| AC-07 | Harness governance invariants | always-loaded-budget.json unchanged; foreign entries in .codex/config.toml and ~/.grok/config.toml untouched<sup>14</sup> |

### Open Architectural Questions for Agent Pushback

Review the existing codebase before finalizing implementation and challenge any default below where local evidence supports a better design:

1.  Should the future pipx CLI (chaosengine-harness planned in \#8058<sup>13</sup>) share the exact zero-dependency ce_ui.py renderer permanently rather than introducing rich as an optional dependency, preserving 100% parity between curl \| sh and chaosengine init?

2.  Is automatic clipboard overwriting on failure (REQ-AI-01) the right ergonomic trade-off, or would a non-blocking prompt (Copy prompt? \[y/N\] only when /dev/tty is open and --non-interactive is unset) or printing a short ce-copy / cat command respect user clipboard state better?

3.  When Codex, Claude, and Grok are installed alongside inactive tools (Gemini not on PATH), should inactive tools move out of the primary summary entirely unless --verbose is passed?

4.  After inspecting assets/brand/lockup-light.svg locally<sup>1</sup>, is a static Python string table generated at CI time (scripts/ci/) preferable to dynamic SVG parsing so runtime bootstrap remains minimal?

5.  Given prior cases where status --json returned healthy while doctor --json exited 1 with CE_DIAGNOSTIC_UNAVAILABLE<sup>15</sup>, should any non-zero doctor gate automatically trigger the failure-recovery panel even if Steps 1–4 succeeded?

#### Works cited

1.  ChaosEngine: a standalone agentic harness for everyone ... - GitHub, [<u>https://github.com/ShaftHQ/chaosengine-harness</u>](https://github.com/ShaftHQ/chaosengine-harness)

2.  [<u>unknown_url</u>](http://docs.google.com/unknown_url)

3.  Install Claude Code: Download & Setup Guide for macOS, Windows, [<u>https://www.morphllm.com/install-claude-code</u>](https://www.morphllm.com/install-claude-code)

4.  Installation \| uv - Astral Docs, [<u>https://docs.astral.sh/uv/getting-started/installation/</u>](https://docs.astral.sh/uv/getting-started/installation/)

5.  Installing mise, [<u>https://mise.jdx.dev/installing-mise.html</u>](https://mise.jdx.dev/installing-mise.html)

6.  Windows: Python not using ANSI compatible console \#73245 - GitHub, [<u>https://github.com/python/cpython/issues/73245</u>](https://github.com/python/cpython/issues/73245)

7.  List of terminal emulators that support hyperlinks (OSC 8 ... - GitHub, [<u>https://github.com/Alhadis/OSC8-Adoption/</u>](https://github.com/Alhadis/OSC8-Adoption/)

8.  OSC 8 \| vtdn, [<u>https://vtdn.dev/docs/osc/osc8</u>](https://vtdn.dev/docs/osc/osc8)

9.  [<u>https://raw.githubusercontent.com/ShaftHQ/chaosengine-harness/main/bootstrap.py</u>](https://raw.githubusercontent.com/ShaftHQ/chaosengine-harness/main/bootstrap.py)

10. [<u>https://raw.githubusercontent.com/ShaftHQ/chaosengine-harness/main/install.sh</u>](https://raw.githubusercontent.com/ShaftHQ/chaosengine-harness/main/install.sh)

11. [<u>https://shafthq.github.io/docs/agentic/chaos-engine</u>](https://shafthq.github.io/docs/agentic/chaos-engine)

12. [<u>https://github.com/ShaftHQ/chaosengine-harness/tree/main/assets</u>](https://github.com/ShaftHQ/chaosengine-harness/tree/main/assets)

13. Spec: one-command install and guided setup for ChaosEngine, [<u>https://github.com/ShaftHQ/SHAFT_ENGINE/issues/8058</u>](https://github.com/ShaftHQ/SHAFT_ENGINE/issues/8058)

14. Spec: adopt Craft Anything ideas into ChaosEngine harness \#8062, [<u>https://github.com/ShaftHQ/SHAFT_ENGINE/issues/8062</u>](https://github.com/ShaftHQ/SHAFT_ENGINE/issues/8062)

15. restore local ChaosEngine health and harden installer · Issue \#5354, [<u>https://github.com/ShaftHQ/SHAFT_ENGINE/issues/5354</u>](https://github.com/ShaftHQ/SHAFT_ENGINE/issues/5354)

16. merge Coach · The Orchestrator profile, role and skills into ... - GitHub, [<u>https://github.com/ShaftHQ/SHAFT_ENGINE/issues/7897</u>](https://github.com/ShaftHQ/SHAFT_ENGINE/issues/7897)

17. move ChaosEngine to a standalone repo + role-based user guide \#40, [<u>https://github.com/ShaftHQ/chaosengine-harness/issues/40</u>](https://github.com/ShaftHQ/chaosengine-harness/issues/40)

18. Console API — Rich 14.1.0 documentation, [<u>https://rich.readthedocs.io/en/latest/console.html</u>](https://rich.readthedocs.io/en/latest/console.html)

19. NO_COLOR: disabling ANSI color output by default, [<u>https://no-color.org/</u>](https://no-color.org/)

20. How to install uv \| pydevtools - Python Developer Tooling Handbook, [<u>https://pydevtools.com/handbook/how-to/how-to-install-uv/</u>](https://pydevtools.com/handbook/how-to/how-to-install-uv/)

21. How to Install Claude Code \| Orchestra, [<u>https://www.getorchestra.io/knowledge-hub/data-tools/claude-code-install</u>](https://www.getorchestra.io/knowledge-hub/data-tools/claude-code-install)

22. Installer options \| uv - Astral Docs, [<u>https://docs.astral.sh/uv/reference/installer/</u>](https://docs.astral.sh/uv/reference/installer/)

23. quick-install.sh - b33eep/claude-code-setup · GitHub, [<u>https://github.com/b33eep/claude-code-setup/blob/main/quick-install.sh</u>](https://github.com/b33eep/claude-code-setup/blob/main/quick-install.sh)

24. uv installation via cargo fails · Issue \#14835 · astral-sh/uv - GitHub, [<u>https://github.com/astral-sh/uv/issues/14835</u>](https://github.com/astral-sh/uv/issues/14835)

25. \[FEATURE\] OSC 8 Hyperlinks for Clickable File Paths \#13008 - GitHub, [<u>https://github.com/anthropics/claude-code/issues/13008</u>](https://github.com/anthropics/claude-code/issues/13008)

26. rich.console — Rich 14.1.0 documentation, [<u>https://rich.readthedocs.io/en/stable/reference/console.html</u>](https://rich.readthedocs.io/en/stable/reference/console.html)

27. Full support for OSC8 terminal hyperlinks : IJPL-103740, [<u>https://youtrack-production.pub.aws.intellij.net/projects/IJPL/issues/IJPL-103740/Full-support-for-OSC8-terminal-hyperlinks</u>](https://youtrack-production.pub.aws.intellij.net/projects/IJPL/issues/IJPL-103740/Full-support-for-OSC8-terminal-hyperlinks)

28. GNOME Terminal, [<u>https://terminaltrove.com/terminals/gnome-terminal/</u>](https://terminaltrove.com/terminals/gnome-terminal/)

29. Pre-populate issue forms HTTP supplied values \#15477 - GitHub, [<u>https://github.com/orgs/community/discussions/15477</u>](https://github.com/orgs/community/discussions/15477)

30. Syntax for GitHub's form schema, [<u>https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-requests/syntax-for-githubs-form-schema</u>](https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-requests/syntax-for-githubs-form-schema)

31. Creating an issue - GitHub Docs, [<u>https://docs.github.com/articles/creating-an-issue</u>](https://docs.github.com/articles/creating-an-issue)

32. Using query parameters to create a pull request - GitHub Docs, [<u>https://docs.github.com/en/pull-requests/reference/using-query-parameters-to-create-a-pull-request</u>](https://docs.github.com/en/pull-requests/reference/using-query-parameters-to-create-a-pull-request)

33. \[ChaosEngine installer\] CE-INSTALL-FAILED · Issue \#5352 - GitHub, [<u>https://github.com/ShaftHQ/SHAFT_ENGINE/issues/5352</u>](https://github.com/ShaftHQ/SHAFT_ENGINE/issues/5352)

34. Grok Code: cut duplicate CE context (CLAUDE+AGENTS markers, [<u>https://github.com/ShaftHQ/SHAFT_ENGINE/issues/5802</u>](https://github.com/ShaftHQ/SHAFT_ENGINE/issues/5802)

35. Spec: adopt CUGA ideas into ChaosEngine harness \#8032 - GitHub, [<u>https://github.com/ShaftHQ/SHAFT_ENGINE/issues/8032</u>](https://github.com/ShaftHQ/SHAFT_ENGINE/issues/8032)
