# -*- coding: utf-8 -*-
"""OpenCLI backend probing.

OpenCLI (github.com/jackwener/opencli) drives the user's real Chrome via a
browser-bridge extension + local daemon, reusing existing login sessions —
zero per-platform configuration, desktop-only (no headless).

Probing notes (verified live):
  - `opencli doctor` AUTO-STARTS the daemon — a side effect, so health
    checks must use `opencli daemon status` (pure query) instead.
  - Exit codes are always 0; status must be parsed from text output.
  - "Extension: disconnected" does NOT mean unusable: the extension's
    service worker sleeps and any real opencli command wakes it up
    (verified: status flips disconnected→connected after one call).
    Since daemon status can't tell "sleeping" from "never installed",
    we check Chrome's Extensions directory on disk to disambiguate.
"""

import glob
import os
import time
from dataclasses import dataclass

from agent_reach.probe import probe_command

OPENCLI_PACKAGE = "@jackwener/opencli"
OPENCLI_EXTENSION_ID = "ildkmabpimmkaediidaifkhjpohdnifk"
OPENCLI_EXTENSION_URL = (
    f"https://chromewebstore.google.com/detail/opencli/{OPENCLI_EXTENSION_ID}"
)

#: Chrome-family profile roots that contain <Profile>/Extensions/<id>/
_CHROME_PROFILE_ROOTS = (
    "~/Library/Application Support/Google/Chrome",                # macOS Chrome
    "~/Library/Application Support/Chromium",                     # macOS Chromium
    "~/Library/Application Support/Microsoft Edge",               # macOS Edge
    "~/Library/Application Support/BraveSoftware/Brave-Browser",  # macOS Brave
    "~/.config/google-chrome",                                    # Linux Chrome
    "~/.config/chromium",                                         # Linux Chromium
    "~/.config/microsoft-edge",                                   # Linux Edge
    "~/.config/BraveSoftware/Brave-Browser",                      # Linux Brave
)


def _extension_installed_on_disk() -> bool:
    """True if the OpenCLI extension exists in any Chrome profile.

    Store-installed extensions always live under
    <profile>/Extensions/<extension id>/ — this disambiguates a sleeping
    service worker from a never-installed extension. Dev installs via
    "Load unpacked" are not covered (those users can read `opencli doctor`).
    """
    roots = [os.path.expanduser(p) for p in _CHROME_PROFILE_ROOTS]
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:  # Windows
        for parts in (
            ("Google", "Chrome", "User Data"),
            ("Microsoft", "Edge", "User Data"),
            ("Chromium", "User Data"),
            ("BraveSoftware", "Brave-Browser", "User Data"),
        ):
            roots.append(os.path.join(local_app_data, *parts))
    for root in roots:
        if glob.glob(os.path.join(root, "*", "Extensions", OPENCLI_EXTENSION_ID)):
            return True
    return False


@dataclass
class OpenCLIStatus:
    installed: bool = False
    broken: bool = False
    daemon_running: bool = False
    extension_connected: bool = False
    extension_installed: bool = False
    version: str = ""
    hint: str = ""

    @property
    def ready(self) -> bool:
        """Usable now or on first call.

        A live connection counts, and so does an installed-but-sleeping
        extension: its service worker wakes on the first real command.
        """
        return self.installed and not self.broken and (
            self.extension_connected or self.extension_installed
        )


#: Memo TTL: short enough that a long-running MCP server's get_status re-probes
#: OpenCLI's live daemon/extension state (CR-014 — the tool advertises "live
#: diagnostics, not a cached read"), long enough that the 4 channels within a
#: single doctor/install run still share one probe.
_STATUS_TTL_SECONDS = 45
_status_memo: dict = {"value": None, "at": 0.0}


def opencli_status(timeout: int = 10) -> OpenCLIStatus:
    """Probe OpenCLI install + daemon/extension state without side effects.

    Memoized with a short TTL for the default timeout: opencli_status() is called
    independently by four channels (twitter, reddit, xiaohongshu, bilibili) on
    every doctor/install run, each call spawning two 10s-timeout subprocesses —
    without caching a wedged daemon socket could stall doctor up to ~80s. The TTL
    (_STATUS_TTL_SECONDS) means a long-running MCP server re-probes rather than
    serving state frozen at startup. Call reset_opencli_status_cache() to force an
    immediate re-probe. A non-default timeout bypasses the memo.
    """
    if timeout != 10:
        return _probe_opencli_status(timeout)
    now = time.monotonic()
    cached = _status_memo["value"]
    if cached is None or (now - _status_memo["at"]) > _STATUS_TTL_SECONDS:
        _status_memo["value"] = _probe_opencli_status(10)
        _status_memo["at"] = now
    return _status_memo["value"]


def reset_opencli_status_cache() -> None:
    """Clear the opencli_status() memo (tests / forced live re-probe)."""
    _status_memo["value"] = None
    _status_memo["at"] = 0.0


def _probe_opencli_status(timeout: int = 10) -> OpenCLIStatus:
    """Probe OpenCLI install + daemon/extension state without side effects."""
    version_probe = probe_command(
        "opencli", ["--version"], timeout=timeout, package=OPENCLI_PACKAGE
    )
    if version_probe.status == "missing":
        return OpenCLIStatus(installed=False)
    if not version_probe.ok:
        return OpenCLIStatus(
            installed=True,
            broken=True,
            hint=(
                "opencli 命令存在但无法执行（node 环境损坏），重装：\n"
                f"  npm install -g {OPENCLI_PACKAGE}"
            ),
        )

    st = OpenCLIStatus(installed=True, version=version_probe.output.strip())

    daemon_probe = probe_command(
        "opencli", ["daemon", "status"], timeout=timeout, package=OPENCLI_PACKAGE
    )
    output = daemon_probe.output if daemon_probe.ok else ""
    # `opencli daemon status` prints lines like:
    #   Daemon: running (PID 37389) / Daemon: not running
    #   Extension: connected / Extension: disconnected
    for line in output.splitlines():
        line = line.strip().lower()
        if line.startswith("daemon:"):
            st.daemon_running = "not running" not in line and "running" in line
        elif line.startswith("extension:"):
            st.extension_connected = "disconnected" not in line and "connected" in line

    if not st.extension_connected:
        st.extension_installed = _extension_installed_on_disk()
        if not st.extension_installed:
            st.hint = (
                "OpenCLI 已安装，但 Chrome 扩展未安装。\n"
                f"  1. 安装扩展（需手动点一次）：{OPENCLI_EXTENSION_URL}\n"
                "  2. 保持 Chrome 打开，运行 `opencli doctor` 验证"
            )
    return st


def opencli_summary(st: OpenCLIStatus) -> str:
    """One-line state description for channel messages / install output."""
    if not st.installed:
        return "OpenCLI 未安装"
    if st.broken:
        return "OpenCLI 无法执行（node 环境损坏）"
    if st.extension_connected:
        return f"OpenCLI 可用（浏览器登录态，v{st.version}）"
    if st.ready:
        return "OpenCLI 可用（扩展睡眠中，调用时自动唤醒）"
    if st.daemon_running:
        return "OpenCLI 已安装，等待 Chrome 扩展安装"
    return "OpenCLI 已安装（daemon 未运行，使用时自动启动；需 Chrome 扩展）"
