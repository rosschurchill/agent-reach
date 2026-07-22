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
        stdout = ""
        stderr = ""

    with patch("subprocess.run", return_value=R()) as run:
        ok = cli._run_vendored_nodesource_setup()
    assert ok is True
    # It ran `bash <vendored script>`, not a curl of a remote URL.
    (cmd,), _ = run.call_args
    assert cmd[0] == "bash"
    assert cmd[1].endswith("nodesource_setup_22.x.sh")


def test_checksum_parser_accepts_both_sha256sum_formats(tmp_path, monkeypatch):
    """CR-012: text-mode ('digest  name') and binary-mode ('digest *name')."""
    scripts = tmp_path
    (scripts / "CHECKSUMS.sha256").write_text(
        "# comment\n"
        "aaaa1111  text_mode.sh\n"
        "bbbb2222 *binary_mode.sh\n"
        "cccc3333\ttab_sep.sh\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "_scripts_dir", lambda: str(scripts))
    sums = cli._load_script_checksums()
    assert sums["text_mode.sh"] == "aaaa1111"
    assert sums["binary_mode.sh"] == "bbbb2222"   # leading '*' stripped
    assert sums["tab_sep.sh"] == "cccc3333"


def test_in_code_pin_catches_manifest_only_swap(tmp_path, monkeypatch):
    """CR-013: rewriting BOTH the script and the co-located manifest still fails
    because the in-code _SCRIPT_PINS anchor doesn't match."""
    scripts = tmp_path
    evil = b"#!/bin/bash\nrm -rf /\n"
    import hashlib
    evil_digest = hashlib.sha256(evil).hexdigest()
    (scripts / "transcribe_xiaoyuzhou.sh").write_bytes(evil)
    # Attacker also rewrote the manifest to match their evil script:
    (scripts / "CHECKSUMS.sha256").write_text(
        f"{evil_digest}  transcribe_xiaoyuzhou.sh\n", encoding="utf-8"
    )
    monkeypatch.setattr(cli, "_scripts_dir", lambda: str(scripts))
    # Manifest agrees, but the in-code pin does not → refuse.
    assert cli._verify_vendored_script("transcribe_xiaoyuzhou.sh") is False
