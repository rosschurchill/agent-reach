#!/bin/bash
# Agent Reach — end-to-end integration test (router model).
#
# Installs THIS checkout into a clean venv, runs install(safe) + doctor, then
# exercises the REAL upstream read commands the SKILL prescribes for the
# zero-config channels (agent-reach is a router/installer, not a wrapper — there
# is no `agent-reach read`; the agent calls the upstream tool directly).
#
# Login channels (Twitter / Reddit / XiaoHongShu / Xueqiu / LinkedIn) need a
# browser-cookie export and are intentionally skipped here — see docs/install.md.
#
# Usage: bash test.sh
set -e

REPO="$(cd "$(dirname "$0")" && pwd)"

echo "╔════════════════════════════════════════════╗"
echo "║   👁️  Agent Reach — integration test        ║"
echo "╚════════════════════════════════════════════╝"

echo "📦 clean venv..."
TEST_DIR=$(mktemp -d)
python3 -m venv "$TEST_DIR/venv"
# shellcheck disable=SC1091
source "$TEST_DIR/venv/bin/activate"

echo "📥 install the hardened build from $REPO ..."
pip install -q "$REPO"

echo "⚙️  agent-reach install (safe mode — no system changes)..."
agent-reach install --env=auto --safe 2>&1 | tail -4 || true

echo "🩺 agent-reach doctor..."
agent-reach doctor 2>&1 | tail -18

echo ""
echo "📖 zero-config read smoke (real upstream commands)"
PASS=0; FAIL=0; SKIP=0
ok()   { echo "  ✅ $1"; PASS=$((PASS+1)); }
skip() { echo "  ⏭️  $1 ($2)"; SKIP=$((SKIP+1)); }
fail() { echo "  ❌ $1 — $2"; FAIL=$((FAIL+1)); }

# Web — Jina Reader
out=$(curl -s --max-time 25 "https://r.jina.ai/https://example.com" || true)
echo "$out" | grep -qi "Test Document" && ok "Web (Jina Reader)" || fail "Web" "$(echo "$out" | head -1)"

# GitHub — gh CLI
if command -v gh >/dev/null 2>&1; then
    gh repo view cli/cli >/dev/null 2>&1 && ok "GitHub (gh)" || skip "GitHub" "gh not authenticated"
else
    skip "GitHub" "gh not installed"
fi

# RSS — feedparser (a package dependency)
python -c "import feedparser,sys; d=feedparser.parse('https://hnrss.org/frontpage'); sys.exit(0 if d.entries else 1)" \
    && ok "RSS (feedparser)" || fail "RSS" "no entries"

# V2EX — public JSON API
curl -s --max-time 20 "https://www.v2ex.com/api/topics/hot.json" | grep -q '"title"' \
    && ok "V2EX (public API)" || fail "V2EX" "no topics"

# YouTube — yt-dlp (a package dependency)
if command -v yt-dlp >/dev/null 2>&1; then
    yt-dlp --dump-json --no-warnings "https://www.youtube.com/watch?v=dQw4w9WgXcQ" 2>/dev/null | grep -q '"title"' \
        && ok "YouTube (yt-dlp)" || fail "YouTube" "no metadata"
else
    skip "YouTube" "yt-dlp not installed"
fi

# Bilibili search — public API (WAF-gated; failure is a skip, not a hard fail)
UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
curl -s --max-time 15 -c "$TEST_DIR/bili.txt" -o /dev/null -A "$UA" "https://www.bilibili.com/" || true
if curl -s --max-time 15 -b "$TEST_DIR/bili.txt" -A "$UA" -e "https://www.bilibili.com/" \
     "https://api.bilibili.com/x/web-interface/search/all/v2?keyword=AI&page=1" | grep -q '"code":0'; then
    ok "Bilibili search (public API)"
else
    skip "Bilibili search" "WAF/rate-limited from this IP"
fi

echo "  ⏭️  Twitter · Reddit · XiaoHongShu · Xueqiu · LinkedIn — need browser cookies (docs/install.md)"
SKIP=$((SKIP+5))

echo ""
echo "════════════════════════════════════════════"
echo "  ✅ passed: $PASS   ❌ failed: $FAIL   ⏭️  skipped: $SKIP"
echo "════════════════════════════════════════════"

deactivate 2>/dev/null || true
rm -rf "$TEST_DIR"

if [ "$FAIL" -eq 0 ]; then
    echo "🎉 zero-config channels verified end-to-end"
else
    echo "⚠️  $FAIL check(s) failed — see output above"
    exit 1
fi
