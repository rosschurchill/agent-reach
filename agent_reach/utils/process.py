"""Subprocess helpers for consistent cross-platform text handling."""

from __future__ import annotations

import os
from collections.abc import Mapping

UTF8_ENV = {
    "PYTHONUTF8": "1",
    "PYTHONIOENCODING": "utf-8",
}

#: When no explicit base is given we build the child env from an allowlist of
#: os.environ rather than cloning the whole parent env — so unrelated secrets a
#: user has exported don't leak into every probed third-party CLI (CR-006/AR-006).
_ENV_ALLOWLIST = (
    # System / locale / path resolution the probed binaries need to run.
    "PATH", "HOME", "USER", "LANG", "LC_ALL", "LC_MESSAGES", "LC_CTYPE",
    "TERM", "TMPDIR", "TEMP", "TMP",
    # Windows equivalents.
    "SystemRoot", "ComSpec", "PATHEXT", "APPDATA", "LOCALAPPDATA", "USERPROFILE",
    # Network reachability — the product's own design tells agents to export
    # HTTP(S)_PROXY on restricted networks (cli.py --proxy). Dropping these made
    # doctor probes run proxyless and report false timeouts (CR-004).
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ALL_PROXY",
    "http_proxy", "https_proxy", "no_proxy", "all_proxy",
    # TLS trust roots — a custom CA bundle must reach the child or HTTPS probes
    # fail with cert errors that read as auth failures.
    "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "NODE_EXTRA_CA_CERTS",
    # XDG dirs — some CLIs read their config/creds/state from here.
    "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME",
    # Agent Reach's own toggle.
    "AGENT_REACH_LANG",
    # NOTE: credentials are deliberately NOT here. The default env is handed to
    # EVERY probed third-party CLI, so a token in this list would leak to opencli/
    # yt-dlp/mcporter/etc. on an unrelated probe (CR-004). Each secret is injected
    # only at the probe that owns it, via probe_command(extra_env=...).
)


def utf8_subprocess_env(base: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return an environment that forces Python child processes into UTF-8 mode.

    With no `base`, the child env is built from an allowlist of the parent
    environment (see `_ENV_ALLOWLIST`) instead of a full copy, so unrelated
    exported secrets are not handed to probed third-party CLIs. Callers that
    need more variables must pass them explicitly via `base`. UTF-8 forcing is
    always overlaid last.
    """
    if base is None:
        env = {k: os.environ[k] for k in _ENV_ALLOWLIST if k in os.environ}
    else:
        env = dict(base)
    env.update(UTF8_ENV)
    return env


def creds_from_env(*names: str) -> dict[str, str]:
    """Pick just these variables out of os.environ (skipping unset ones).

    Use at a probe call site to hand a tool ONLY its own credentials via
    probe_command(extra_env=...), instead of putting secrets in the shared
    default allowlist where they'd reach every probed CLI (CR-004).
    """
    return {n: os.environ[n] for n in names if n in os.environ}


def mcporter_utf8_env_args() -> list[str]:
    """Return mcporter --env arguments for UTF-8 Python stdio servers."""
    args = []
    for key, value in UTF8_ENV.items():
        args.extend(["--env", f"{key}={value}"])
    return args
