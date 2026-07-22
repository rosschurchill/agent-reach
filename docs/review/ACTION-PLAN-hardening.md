# agent-reach — Hardening Action Plan

**Source:** the 2026-07-22 `/ai-scan` of upstream `Panniantong/agent-reach` (Prompt Inquisitor +
Runtime Guardian + manual verification). Full findings in
`docs/handoff/HANDOVER-agent-reach-2026-07-22.md`.
**Working copy:** this fork, branch `hardening`, pinned to `v1.5.0` = `f65526cbaaad3879473acc1ba6dbefd195caf2be`.
**Scan verdict being remediated:** CONDITIONAL → target CLEAR. No malware/backdoor/exfil found; these
are design + supply-chain hardening changes. Do all work on `hardening`; show diffs before commit.

## Ticket summary
Status legend: **Done** = fix landed + acceptance command run · **In Progress** · **Not Started**.
(CR-### cross-references are the `/graph-review` tickets in `.claude-review/REMEDIATION.md` that carried out the work.)

| ID | Sev | Title | Phase | Status |
|----|-----|-------|-------|--------|
| AR-001 | MED | Remove remote `main`-branch fetch-and-follow; vendor install/update docs | 1 | **Done** (CR-001/002; acceptance grep = 0) |
| AR-002 | MED | Remove the self-update `check-update` nudge from the skill | 1 | **Done** (CR-001) |
| AR-003 | MED | Narrow XHS/Xueqiu cookie capture to named tokens | 2 | **Done** (FX-202; live smoke recommended) |
| AR-004 | LOW | Align guide docs to the SHA-pinned tooling (rdt-cli); pin mcporter/linkedin-mcp | 2 | **Done** (FX-203; `mcporter@0.12.0`, `linkedin-scraper-mcp==4.14.0`) |
| AR-005 | LOW | Make `get_status` MCP tool side-effect-free (or label it) | 3 | **Done** (FX-204; labelled) |
| AR-006 | INFO | Pass an allow-listed env to probed child processes | 3 | **Done** (CR-006) |
| AR-007 | INFO | Make the remote `exa` MCP endpoint opt-in + documented | 3 | **Done** (FX-205; opt-in via `--channels exa`) |
| AR-008 | — | Add our security gate (deps pin check + scan) + document trust boundary | 4 | **Done** (FX-206; CI pin-guard + trust docs) |

> Also landed beyond the original AR list, via the `/graph-review` remediation: **CR-003** (stop echoing
> GitHub release-note bodies into agent context), **CR-004** (guard non-JSON HTTP 200 in check-update/watch),
> **CR-005** (the `transcribe.py` SSRF/arg-injection guard — found *missing*, now added), **CR-007/008**
> (OpenCLI probe memoization + Edge/Brave/Chromium detection), **CR-009–012** (backend-override + twitter
> probe hardening).

---

## Phase 1 — cut the remote-follow surface (highest value, mechanical)

### AR-001 — Remove `raw.githubusercontent…/main/…` fetch-and-follow (MED, top finding)
**Why:** the skill instructs the agent to fetch `…/main/docs/install.md` (and `update.md`) and execute
its steps. Whoever controls `main` (or a MITM) can change those instructions later → indirect prompt
injection / supply-chain hijack of the very cookies+keys this tool handles.
**Files / lines (agent-facing — must fix):**
- `agent_reach/skill/SKILL.md:55, 130`
- `agent_reach/skill/SKILL_en.md:45, 123`
- `agent_reach/cli.py:1652, 1801` (printed upgrade lines)
**Files (docs surface — fix for consistency):** `README.md`, `docs/install.md`, `docs/update.md`,
`docs/README_en.md`, `docs/README_ja.md`, `docs/README_ko.md`.
**Change:** the repo already *contains* `docs/install.md` / `docs/update.md`. Stop referencing the
**remote** copy: rewrite each reference to the local vendored path (e.g. "see `docs/install.md` in
this repo"), or delete the "fetch this URL and follow it" instruction outright. The agent must never
be told to pull setup/upgrade instructions from a network URL at runtime.
**Acceptance:** `grep -rn "raw.githubusercontent.com/Panniantong/agent-reach/main" agent_reach/` →
**0 hits**; docs reference local paths only. Manual read of SKILL.md confirms no "fetch & follow
remote" step remains.

### AR-002 — Remove the self-update nudge (MED)
**Why:** skill tells the agent to run `agent-reach check-update` after big tasks and inject an upgrade
prompt seeding the user a copy-paste line pointing back at `main/docs/update.md` (feeds AR-001).
**Files / lines:** `agent_reach/skill/SKILL.md:53`, `agent_reach/skill/SKILL_en.md:42`; the
`check-update` command itself lives at `cli.py:116, 125, 148-149, 1677` and the printed lines at
`cli.py:1652, 1801`.
**Change:** delete the "run check-update and nudge the user" instruction from both SKILL files.
Keep the `check-update` CLI command available for manual use, but it must not emit a remote-follow
URL (covered by AR-001). Updates happen via our controlled fork bump.
**Acceptance:** no `check-update` auto-nudge text in either SKILL file; `check-update` output contains
no `raw.githubusercontent…/main/…` URL.

---

## Phase 2 — bound capabilities & pin tooling

### AR-003 — Narrow cookie capture to named tokens (MED)
**Why:** for XiaoHongShu & Xueqiu the extractor grabs the **entire** cookie set, broader than needed.
**Files / lines:** `agent_reach/cookie_extract.py:26` (`"cookies": None,  # None = grab all…`),
`:38` (`"cookies": None,  # grab all — xq_a_token + session cookies required`).
**Change:** replace `None` with the explicit named cookies each service needs (mirror the
Twitter/Bilibili named-token pattern). Keep the existing `0o600` writes and `shlex.quote` handling.
**Acceptance:** no `"cookies": None` remains; extraction returns only the named tokens; existing
cookie-config flow still works (manual smoke on one platform).

### AR-004 — Align docs to SHA-pinned tooling; pin the rest (LOW)
**Why:** the code already pins rdt-cli (`cli.py:21`, `reddit.py:22` → `@5e4fb37…`), but the docs still
tell the agent the **unpinned** form, and mcporter / linkedin-scraper-mcp are unpinned.
**Files / lines:**
- Unpinned in docs: `agent_reach/guides/setup-reddit.md:22`, `agent_reach/skill/references/social.md:227`
  (both `pipx install 'git+…/rdt-cli.git'` with no SHA).
- Unpinned tooling: `agent_reach/guides/setup-exa.md:15` + `channels/exa_search.py:27` +
  `channels/linkedin.py:9` (`npm install -g mcporter`), `channels/linkedin.py:28,41`
  (`pip install linkedin-scraper-mcp`).
**Change:** update the doc install commands to the exact SHA already used in code
(`git+…/rdt-cli.git@5e4fb37…`). Pin `mcporter` and `linkedin-scraper-mcp` to exact,
≥30-day-old versions; record all external tool pins in a `constraints.txt` (verify each with
`/pin-check`).
**Acceptance:** every `pipx/pip/npm install` string in docs & code carries an exact version/SHA;
`constraints.txt` exists and lists them; `/pin-check` passes.

---

## Phase 3 — tighten runtime blast radius (defense-in-depth)

### AR-005 — `get_status` side effects (LOW/INFO)
**Why:** the one MCP tool, `get_status`, isn't passive — `check_all` spawns probe subprocesses and
makes outbound HTTP to third-party APIs (e.g. `channels/xueqiu.py` hits `stock.xueqiu.com`).
**Files:** `agent_reach/integrations/mcp_server.py` (tool), `agent_reach/core.py` (`check_all`), channel `check()` methods.
**Change:** either serve cached/last-known status from the tool, or update the tool description to
state it performs live network probes so an agent isn't surprised by egress from a "status" call.
**Acceptance:** tool description matches actual behaviour, or `get_status` no longer triggers network egress.

### AR-006 — Allow-list child-process env (INFO)
**Why:** `agent_reach/utils/process.py:16` (`env = dict(base or os.environ)`) copies the full parent
env — incl. any secrets — into every probed third-party CLI.
**Change:** pass only the variables each probe needs (PATH + the specific token) instead of the whole env.
**Acceptance:** `process.py` builds an explicit allow-listed env; no `dict(os.environ)` full copy into children.

### AR-007 — `exa` remote MCP opt-in (INFO)
**Why:** `config/mcporter.json` registers `exa` at `https://mcp.exa.ai/mcp` — standing data egress.
**Change:** keep but make it opt-in and document the egress in README/CLAUDE.md.
**Acceptance:** README documents the third-party egress (exa, r.jina.ai); exa endpoint not enabled by default.

---

## Phase 4 — our security gate & trust boundary

### AR-008 — CI gate + trust-boundary docs
**Change:** add a `constraints.txt`/lock, a pinned-dependency check + a scan step (medusa or equivalent)
in CI, and a `CLAUDE.md`/README section stating: we track a pinned fork, never upstream `main`; upgrades
are a reviewed SHA bump; external tooling is version-pinned.
**Acceptance:** CI runs on `hardening`; `/ai-scan .` on the fork returns CLEAR (AR-001–004 closed);
trust boundary documented.

---

## Do NOT regress (upstream did these right — keep them)
- `agent_reach/transcribe.py` SSRF guard (`_assert_safe_public_url` + `_BLOCKED_HOSTS`: blocks private
  IPs, localhost, cloud-metadata hosts, non-http schemes).
- List-arg `subprocess.run` everywhere — **no `shell=True` / `os.system`**.
- Credential files written `0o600`; sourceable env values `shlex.quote`'d.
- The single, empty-schema, read-only MCP tool surface.

## Definition of done
All MED tickets (AR-001, AR-002, AR-003) closed + AR-004 pinned; `grep` for the remote-`main` URL is
zero in `agent_reach/`; `/ai-scan .` on the fork → CLEAR; no "do-not-regress" item weakened; changes
committed on `hardening` with diffs reviewed.

## Suggested execution order
AR-001 → AR-002 (Phase 1, mechanical, biggest risk reduction) → AR-004 → AR-003 (Phase 2) →
AR-005/006/007 (Phase 3) → AR-008 (Phase 4). Each ticket = its own commit on `hardening`.
