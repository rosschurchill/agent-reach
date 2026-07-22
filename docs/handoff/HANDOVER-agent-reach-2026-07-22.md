# HANDOVER — agent-reach: fork & harden — 2026-07-22

## Why this project exists
`agent-reach` (github.com/Panniantong/agent-reach, MIT, v1.5.0) is a Python tool that gives an AI
agent read access to 10+ platforms (Twitter/X, Reddit, LinkedIn, XiaoHongShu, YouTube, RSS, web,
etc.). It ships as **a Claude skill + an MCP server**, so a coding agent loads and acts on it. We
want it, but NOT the way upstream distributes it: the skill repeatedly tells the agent to **fetch
Markdown from the floating `main` branch and follow it**, and to install third-party tooling from
unpinned Git branches. That's a standing supply-chain / indirect-prompt-injection surface.

**Plan: fork it, pin it, vendor the docs it fetches, harden it, and run our own copy** — so nothing
is pulled from `main` at agent-runtime and our security risk is bounded to code we've reviewed.

## Security review summary (from the 2026-07-22 /ai-scan)
Full scan was read-only; nothing installed/executed. Verdict: **CONDITIONAL — safe to use with the
hardening below.** No malware, no backdoor, no credential exfiltration, no covert prompt-injection
payload was found. The repo is actually reasonably built (real SSRF guard in `transcribe.py`,
list-arg `subprocess` everywhere — no `shell=True`, cookies written `0o600`, values `shlex.quote`'d).

> Note: `medusa scan` rated it CRITICAL 0/100, but those 35 "criticals" were verified false positives
> (localhost→"cloud-metadata SSRF", denylist/tests flagged as vulns, safe subprocess→"injection",
> etc.). See the medusa repo's `docs/handoff/HANDOVER-medusa-2026-07-22-fp-realworld.md`. The genuine
> findings are the design/supply-chain items below, surfaced by manual + agent review.

### Genuine findings → what we change in the fork
| # | Sev | Finding (upstream) | Fork action |
|---|-----|--------------------|-------------|
| 1 | **MED (top)** | Skill tells the agent to fetch `raw.githubusercontent.com/Panniantong/agent-reach/**main**/docs/install.md` and execute its steps. Also `docs/update.md`. Referenced in `SKILL.md:57,138`, `SKILL_en.md:45,129`, `cli.py:1681,1830`, `docs/install.md:321`, all READMEs. | **Vendor `install.md`/`update.md` into the fork; rewrite every reference to point at the local pinned copy (or delete the fetch-and-follow instruction). No agent-runtime pull from `main`.** |
| 2 | MED | Self-update nudge: skill has the agent run `check-update` after big tasks and seed the user a copy-paste line pointing at `main/docs/update.md`. | Remove the auto-nudge; updates happen via our controlled fork bump, not a remote-doc follow. |
| 3 | MED | Broad "grab ALL cookies" for XiaoHongShu & Xueqiu (`cookie_extract.py:24,36` — `"cookies": None`). | Narrow to named session tokens like the Twitter/Bilibili path; keep the `0o600` writes. |
| 4 | LOW | Unpinned third-party installs the skill tells the agent to run: `pipx install 'git+…/rdt-cli.git'` (social.md:227 / setup-reddit.md:22), `npm install -g mcporter`, `pip install linkedin-scraper-mcp`. | Pin each to an exact, ≥30-day-old version (our supply-chain rule). Record pins in a lockfile / `constraints.txt`. |
| 5 | LOW/INFO | `get_status` MCP tool is not side-effect-free (spawns probe subprocesses + outbound HTTP to third-party APIs). | Make status read cached state, or document that "status" performs network probes. |
| 6 | INFO | `utils/process.py:16` copies the full parent env into every probed CLI (secrets inherited). | Pass an allowlisted env to child processes. |
| 7 | INFO | `config/mcporter.json` registers remote `exa` MCP (`https://mcp.exa.ai/mcp`) — standing data egress. | Keep but document; make it opt-in. |

### Keep (don't regress during the upgrade)
- `transcribe.py` `_assert_safe_public_url()` SSRF guard (blocks private IPs, localhost, metadata hosts, non-http schemes) + `_BLOCKED_HOSTS`.
- List-arg `subprocess.run` everywhere (no `shell=True`/`os.system`).
- `0o600` credential files + `shlex.quote` on sourceable env writes.
- The single, empty-schema, read-only MCP tool surface.

## Fork & harden plan (phased)
**Phase 0 — fork & pin (foundation)**
1. Fork `Panniantong/agent-reach` → our org. Clone into this folder.
2. Pin to the reviewed commit: tag **`v1.5.0` = `f65526cbaaad3879473acc1ba6dbefd195caf2be`**
   (NB: upstream `main` HEAD `1494c2ab…` is *ahead* of v1.5.0 — do NOT track main).
3. `git init` our fork history; record upstream + pinned SHA in this doc / README.

**Phase 1 — cut the remote-follow (finding 1 & 2)**
4. Vendor `docs/install.md` + `docs/update.md` into the fork (they're already in-repo — just stop
   fetching the *remote* copy). Rewrite the ~25 `raw.githubusercontent…/main/…` references to local
   paths or remove the "fetch and follow" instruction from `SKILL.md`, `SKILL_en.md`, `cli.py`, READMEs.
5. Remove the `check-update` self-nudge from the skill.

**Phase 2 — pin third-party tooling (finding 4)**
6. Replace unpinned `git+…/rdt-cli.git`, `npm -g mcporter`, `pip install linkedin-scraper-mcp` with
   exact, ≥30-day-old versions; add a `constraints.txt`/lock and vet each with `/pin-check`.

**Phase 3 — tighten capabilities (findings 3, 5, 6)**
7. Narrow cookie extraction to named tokens; allowlist child-process env; make `get_status` read-only.

**Phase 4 — our security gate**
8. Add CI that runs a pinned-dep check + a scan on our fork; document the trust boundary in README/CLAUDE.md.
9. Re-run `/ai-scan <this-fork>` → expect CONDITIONAL→CLEAR once findings 1–4 are closed.

## Current state
- The working copy is **fully populated**: the pinned `v1.5.0` codebase is present under
  `agent_reach/` in this folder, on branch **`hardening`** with its own git history.
- **Remediation is underway on `hardening`.** A `/graph-review` of `agent_reach/` (verdict
  CONDITIONAL) drove a `/fix-loop` that has landed the security/reliability half of the plan
  (see `docs/review/ACTION-PLAN-hardening.md` for AR-ticket status and `.claude-review/REMEDIATION.md`
  for the CR-ticket plan). Shipped so far: remote fetch-and-follow removed from both SKILL files
  and the CLI update/watch surface (AR-001/002), release-note echo dropped, `resp.json()` guarded,
  child-process env allow-listed (AR-006), OpenCLI probe memoized + Edge/Brave/Chromium detection,
  twitter backend-override + probe hardening.
- **Correction to the "Keep (don't regress)" list above:** the `transcribe.py` SSRF guard it credits
  (`_assert_safe_public_url` + `_BLOCKED_HOSTS`) did **not** actually exist in the pinned tree — verified
  by grep during review. It was *added* as CR-005 (http(s)-only, private/loopback/link-local/metadata
  block, `--` end-of-options on the yt-dlp argv, opt-in local files). Treat that row as a task done, not
  a property preserved.

## Open items
- ☑ GitHub fork created / code present on branch `hardening`.
- ☑ Working copy pinned to `v1.5.0` (`f65526c…`).
- ☐ Remaining ACTION-PLAN tickets (advisory / lower severity): AR-003 cookie scoping,
  AR-004 tooling pins + `constraints.txt`, AR-005 `get_status` labelling, AR-007 exa opt-in,
  AR-008 CI gate + trust-boundary docs. See the advisory follow-ups in `.claude-review/REMEDIATION.md`.
- ☐ Re-run `/ai-scan .` on the fork to confirm CONDITIONAL→CLEAR once AR-003/004 land.

## Next steps
1. Land the remaining Phase 2–4 ACTION-PLAN tickets (cookie scoping, tooling pins, CI gate).
2. Re-run `/graph-review` (or `/ai-scan .`) to confirm the verdict improves.

## Key pointers
- Upstream: `github.com/Panniantong/agent-reach` · pinned `v1.5.0` = `f65526cbaaad3879473acc1ba6dbefd195caf2be` · MIT.
- Remote-follow references to rewrite: `agent_reach/skill/SKILL.md:57,138`, `SKILL_en.md:45,129`, `agent_reach/cli.py:1681,1830`, `docs/install.md:321`, READMEs (zh/en/ja/ko).
- Cookie scope: `agent_reach/cookie_extract.py:24,36`. Env inheritance: `agent_reach/utils/process.py:16`. Remote MCP: `config/mcporter.json`.
- Keep-safe: `agent_reach/transcribe.py` SSRF guard (~lines 88-121).
- Review provenance: medusa `docs/handoff/HANDOVER-medusa-2026-07-22-fp-realworld.md` (why medusa's CRITICAL was noise).
