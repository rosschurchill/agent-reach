# -*- coding: utf-8 -*-
"""The vendored NodeSource setup script must exist and match its reviewed sha256
pin, and the installer must refuse to run a tampered copy. This is the tripwire
that forces a re-review whenever the script changes."""

import hashlib
import pathlib
from unittest.mock import patch

from agent_reach import cli


def _script_path():
    return pathlib.Path(cli.__file__).parent / "scripts" / "nodesource_setup_22.x.sh"


def test_vendored_script_ships_and_matches_pin():
    p = _script_path()
    assert p.is_file(), "vendored NodeSource setup script is missing from the package"
    digest = hashlib.sha256(p.read_bytes()).hexdigest()
    assert digest == cli._NODESOURCE_SETUP_SHA256, (
        "vendored NodeSource script changed without updating _NODESOURCE_SETUP_SHA256 "
        "— re-review the script and bump the pin"
    )


def test_setup_refuses_to_run_on_hash_mismatch(capsys):
    """If the pin doesn't match the file, we must NOT bash the script."""
    with patch.object(cli, "_NODESOURCE_SETUP_SHA256", "0" * 64), patch(
        "subprocess.run"
    ) as run:
        ok = cli._run_vendored_nodesource_setup()
    assert ok is False
    run.assert_not_called()  # never executed the script
    assert "hash verification" in capsys.readouterr().out


def test_setup_runs_vendored_script_when_hash_matches():
    class R:
        returncode = 0

    with patch("subprocess.run", return_value=R()) as run:
        ok = cli._run_vendored_nodesource_setup()
    assert ok is True
    # It ran `bash <vendored script>`, not a curl of a remote URL.
    (cmd,), _ = run.call_args
    assert cmd[0] == "bash"
    assert cmd[1].endswith("nodesource_setup_22.x.sh")
