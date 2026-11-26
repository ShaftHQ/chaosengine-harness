# Compatibility

This package is chaos-engine 1.20261126.0.

`bin/chaos-engine.pyz` bundles `tool.py` and the portable `runtimeFiles` from `distributions.json`. It needs the `python` command on CPython 3.10+. It does not bundle SHAFT `scripts/agents` modules; those files are not in this repository. Discovery manifests are written for Claude Code and Codex. This page does not claim a native client load. Validate the package in the client before relying on it.

| Client | Discovery |
| --- | --- |
| Codex | `.codex-plugin/plugin.json` and `.mcp.json` |
| Claude Code | `.claude-plugin/plugin.json` |
