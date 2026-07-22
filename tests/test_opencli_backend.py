# -*- coding: utf-8 -*-
"""Tests for the OpenCLI cross-channel backend probing."""

from unittest.mock import patch

from agent_reach.backends import (
    opencli_status,
    opencli_summary,
    reset_opencli_status_cache,
)
from agent_reach.probe import ProbeResult


def _status_with(version_probe, daemon_probe=None, ext_on_disk=False):
    """Run opencli_status with probe_command and disk check patched."""
    calls = []

    def fake_probe(cmd, args=("--version",), **kwargs):
        calls.append(list(args))
        if list(args) == ["--version"]:
            return version_probe
        return daemon_probe or ProbeResult("missing")

    # Per-process memo (CR-007) must not leak between tests — force a re-probe.
    reset_opencli_status_cache()
    with patch("agent_reach.backends.opencli.probe_command", side_effect=fake_probe), \
         patch(
             "agent_reach.backends.opencli._extension_installed_on_disk",
             return_value=ext_on_disk,
         ):
        return opencli_status(), calls


def test_not_installed():
    st, _ = _status_with(ProbeResult("missing"))
    assert not st.installed
    assert not st.ready
    assert "未安装" in opencli_summary(st)


def test_broken_node_env_gives_npm_hint():
    st, _ = _status_with(ProbeResult("broken", hint="x"))
    assert st.installed and st.broken
    assert "npm install -g @jackwener/opencli" in st.hint
    assert not st.ready


def test_daemon_running_extension_connected_is_ready():
    daemon_out = "Daemon: running (PID 37389)\nVersion: v1.8.3\nExtension: connected\n"
    st, _ = _status_with(
        ProbeResult("ok", output="1.8.3"),
        ProbeResult("ok", output=daemon_out),
    )
    assert st.installed and st.daemon_running and st.extension_connected
    assert st.ready
    assert "1.8.3" in opencli_summary(st)


def test_extension_never_installed_not_ready_with_store_guide():
    daemon_out = "Daemon: running (PID 1)\nExtension: disconnected\n"
    st, _ = _status_with(
        ProbeResult("ok", output="1.8.3"),
        ProbeResult("ok", output=daemon_out),
        ext_on_disk=False,
    )
    assert st.daemon_running and not st.extension_connected
    assert not st.ready
    assert "chromewebstore.google.com" in st.hint


def test_sleeping_extension_counts_as_ready():
    """实测:扩展 service worker 睡眠时 daemon status 报 disconnected,
    但任何真实命令会唤醒它——装在磁盘上即视为可用。"""
    daemon_out = "Daemon: running (PID 1)\nExtension: disconnected\n"
    st, _ = _status_with(
        ProbeResult("ok", output="1.8.3"),
        ProbeResult("ok", output=daemon_out),
        ext_on_disk=True,
    )
    assert not st.extension_connected
    assert st.extension_installed
    assert st.ready
    assert "唤醒" in opencli_summary(st)
    assert st.hint == ""


def test_daemon_not_running_parsed_correctly():
    st, _ = _status_with(
        ProbeResult("ok", output="1.8.3"),
        ProbeResult("ok", output="Daemon: not running\n"),
    )
    assert st.installed
    assert not st.daemon_running
    assert not st.extension_connected
    assert "自动启动" in opencli_summary(st)


def test_probe_uses_daemon_status_not_doctor():
    """`opencli doctor` auto-starts the daemon (side effect) — health checks
    must only ever call `daemon status`."""
    _, calls = _status_with(
        ProbeResult("ok", output="1.8.3"),
        ProbeResult("ok", output="Daemon: not running\n"),
    )
    assert ["daemon", "status"] in calls
    assert ["doctor"] not in calls


def test_status_is_memoized_per_process():
    """CR-007: repeated default-timeout calls return the cached instance and do
    not re-probe, until the cache is cleared."""
    from agent_reach.backends import opencli
    from agent_reach.backends import opencli_status as status

    reset_opencli_status_cache()
    calls = []

    def fake_probe(cmd, args=("--version",), **kwargs):
        calls.append(list(args))
        return ProbeResult("missing")

    with patch.object(opencli, "probe_command", side_effect=fake_probe):
        a = status()
        b = status()

    assert a is b  # same cached object
    assert calls == [["--version"]]  # probed exactly once, not twice
    reset_opencli_status_cache()


def test_status_memo_expires_after_ttl():
    """CR-014: the memo re-probes after its TTL so a long-running MCP server's
    get_status isn't frozen at startup, but reuses the probe within the TTL."""
    from agent_reach.backends import opencli

    reset_opencli_status_cache()
    calls = []

    def fake_probe(cmd, args=("--version",), **kwargs):
        calls.append(list(args))
        return ProbeResult("missing")

    clock = {"t": 1000.0}
    with patch.object(opencli, "probe_command", side_effect=fake_probe), \
         patch.object(opencli.time, "monotonic", lambda: clock["t"]):
        opencli.opencli_status()          # probe #1
        opencli.opencli_status()          # within TTL → cached
        n_before = len([c for c in calls if c == ["--version"]])
        clock["t"] += opencli._STATUS_TTL_SECONDS + 1
        opencli.opencli_status()          # past TTL → re-probe
        n_after = len([c for c in calls if c == ["--version"]])

    assert n_before == 1          # second call was cached
    assert n_after == 2           # re-probed after TTL
    reset_opencli_status_cache()


def test_chrome_profile_roots_cover_edge_brave_chromium():
    """CR-008: extension detection must look beyond Google Chrome."""
    from agent_reach.backends import opencli

    assert len(opencli._CHROME_PROFILE_ROOTS) >= 8
    joined = " ".join(opencli._CHROME_PROFILE_ROOTS).lower()
    assert "edge" in joined
    assert "brave" in joined
