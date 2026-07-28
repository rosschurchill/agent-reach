# Functional smoke tests — what's verified, what needs you

Agent Reach is a **router/installer**: after install, the agent runs the upstream
tool directly (there is no `agent-reach read`). "Does a channel work" therefore
means "does the upstream command the SKILL prescribes return real data." Run the
whole zero-config set with `bash test.sh`.

## ✅ Zero-config channels — VERIFIED end-to-end (2026-07)

Each was run live and returned real data:

| Channel | Command (what the agent runs) | Result |
|---|---|---|
| Web | `curl -s https://r.jina.ai/https://example.com` | markdown returned ✓ |
| GitHub | `gh repo view cli/cli` | repo metadata ✓ |
| RSS | `feedparser.parse(<feed>)` | 20 entries ✓ |
| V2EX | `curl https://www.v2ex.com/api/topics/hot.json` | hot topics ✓ |
| YouTube | `yt-dlp --dump-json <url>` | title + subtitle langs ✓ |
| Bilibili (search) | `curl …/x/web-interface/search/all/v2?keyword=…` | `code:0`, results ✓ (WAF-gated by IP) |

No account, cookie, or key required for any of these.

## 🔑 `[NEEDS-YOU]` Login channels — need a browser-cookie export (5 min each)

I can't verify these without your session — they require **your** login. No
passwords: you export the cookie string from a browser where you're already
logged in (use a **burner/dedicated account**). Per channel:

1. **Twitter/X** — log in at x.com → export `auth_token` + `ct0` with
   [Cookie-Editor](https://chromewebstore.google.com/detail/cookie-editor/hlkenndednhfkekhgcdicdfddnkalmdm) →
   `agent-reach configure twitter-cookies "<cookie string>"` (or set
   `TWITTER_AUTH_TOKEN` / `TWITTER_CT0`). Verify: `agent-reach doctor` → Twitter ✅,
   then `twitter status` shows `ok: true`.
2. **Reddit** — desktop: `agent-reach install --channels opencli` (reuses your Chrome
   session, click "add extension" once) → `opencli reddit ...`. Server: `rdt login`
   then `rdt search "query"` / `rdt read POST_ID`.
3. **XiaoHongShu** — desktop OpenCLI (as Reddit), or export cookies →
   `agent-reach configure xhs-cookies "<cookie string>"`. Verify a note read.
4. **Xueqiu** — export cookies (must include `xq_a_token`) →
   `agent-reach configure --from-browser chrome` picks them up. Verify: doctor → Xueqiu ✅
   + a real quote fetch.
5. **LinkedIn** — public pages work via Jina Reader with no setup; full profiles need
   `linkedin-scraper-mcp==4.14.0` + its own login (`mcporter config add linkedin ...`).

### The cookie-narrowing caveat (AR-003)
XHS/Xueqiu cookie capture is narrowed to a named allowlist (hardening). If a login
imports but auth then fails, a rotated cookie name may be missing — the extractor
prints the **dropped cookie names** (not values) to stderr; add the missing one to
`PLATFORM_SPECS` in `agent_reach/cookie_extract.py`. This is the one place a live
login could surface a gap.

## Transcription (Xiaoyuzhou / YouTube-no-subs)
Needs a **free** Groq key (not a social account):
`agent-reach configure groq-key gsk_...` → `agent-reach transcribe <url>`.
