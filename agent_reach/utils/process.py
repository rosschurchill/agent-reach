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
    # Agent Reach's own toggle.
    "AGENT_REACH_LANG",
    # Credentials the probed CLIs themselves read from the environment.
    "TWITTER_AUTH_TOKEN", "TWITTER_CT0", "AUTH_TOKEN", "CT0", "GROQ_API_KEY",
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


def mcporter_utf8_env_args() -> list[str]:
    """Return mcporter --env arguments for UTF-8 Python stdio servers."""
    args = []
    for key, value in UTF8_ENV.items():
        args.extend(["--env", f"{key}={value}"])
    return args
