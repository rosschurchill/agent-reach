# CLAUDE.md

## Project
Agent Reach — Python CLI + library that gives AI agents read/search access to 13 internet platforms.
Positioning: installer + doctor + config tool. NOT a wrapper — after install, agents call upstream tools directly.
Repo: github.com/Panniantong/Agent-Reach | License: MIT | Version: 1.5.0

## Commands
- `pip install -e .` — Dev install
- `pytest tests/ -v` — All tests
- `pytest tests/test_cli.py -v` — CLI tests only
- `bash test.sh` — Full integration test (creates venv, installs, runs doctor + channel tests)
- `python -m agent_reach.cli doctor` — Run diagnostics
- `python -m agent_reach.cli install --env=auto` — Auto-configure

## Structure
- `agent_reach/cli.py` — CLI entry point (argparse)
- `agent_reach/core.py` — Core read/search routing logic
- `agent_reach/config.py` — Config management (YAML, env vars)
- `agent_reach/doctor.py` — Diagnostics engine
- `agent_reach/channels/` — One file per platform (twitter.py, reddit.py, youtube.py, etc.)
- `agent_reach/channels/base.py` — Base channel class (all channels inherit from this)
- `agent_reach/integrations/mcp_server.py` — MCP server integration
- `agent_reach/skill/` — OpenClaw skill files
- `agent_reach/guides/` — Usage guides
- `tests/` — pytest tests
- `config/mcporter.json` — MCP tool config

## Conventions
- Python 3.10+ with type hints
- Each channel is a single file in `channels/`, inherits from `BaseChannel`
- Channel contract: must implement `can_handle(url)`, `read(url)`, `search(query)`, `check()` methods
- Use `loguru` for logging, `rich` for CLI output
- Commit format: `type(scope): message` (one commit = one thing)
- All upstream tool calls go through public API/CLI, never hack internals

## Rules
- NEVER modify upstream open source projects' source code
- Agent Reach is a "glue layer" — only route and call, don't reimagine
- Version in THREE places must match: `pyproject.toml`, `__init__.py`, `tests/test_cli.py`
- Always new branch for changes, PR to main, never push to main directly
- Run `pytest tests/ -v` before committing — all tests must pass
- Cookie-based auth (Twitter, XHS): use Cookie-Editor export method only, no QR scan
- XHS login: Cookie-Editor browser export only (QR will hang)

## Trust boundary & data egress
- This is a **hardened fork** of `Panniantong/agent-reach`, pinned to a reviewed commit (`v1.5.0` = `f65526c…`). We **never track upstream `main`** — upgrades are a reviewed SHA bump, not a runtime fetch.
- The skill/CLI must **never** fetch setup/upgrade instructions from a network URL at agent-runtime; reference the vendored `docs/install.md` / `docs/update.md` instead.
- External runtime tools are **version-pinned** and recorded in `constraints.txt`: `mcporter@0.12.0`, `linkedin-scraper-mcp==4.14.0`, `rdt-cli @5e4fb37…`. New pins must be exact and ≥30 days old (`/pin-check`).
- **Third-party egress** (keep documented, don't silently add more): Exa search `mcp.exa.ai` (opt-in via `--channels exa` only), web reads `r.jina.ai`, and live availability probes to each platform from `doctor` / MCP `get_status`.
- Credentials stay local (`~/.agent-reach/config.yaml`, 0o600, atomic writes); cookie capture is limited to named auth/session tokens per platform.
