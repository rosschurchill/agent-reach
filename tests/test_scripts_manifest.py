# -*- coding: utf-8 -*-
"""Integrity manifest for every shipped script (agent_reach/scripts/CHECKSUMS.sha256).

This is the tripwire: if ANY script's bytes change, or a script is added or
removed, without updating CHECKSUMS.sha256, this test fails — forcing a conscious
re-review + re-pin. Covers the vendored third-party NodeSource script AND our own
transcribe_xiaoyuzhou.sh (and anything added later)."""

import hashlib
import pathlib

from agent_reach import cli

SCRIPTS = pathlib.Path(cli.__file__).parent / "scripts"
MANIFEST = SCRIPTS / "CHECKSUMS.sha256"


def _parse_manifest():
    pinned = {}
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        digest, _, name = line.partition("  ")
        pinned[name.strip()] = digest.strip()
    return pinned


def test_manifest_exists():
    assert MANIFEST.is_file(), "scripts/CHECKSUMS.sha256 is missing"


def test_manifest_covers_exactly_the_scripts_dir():
    """No script is unlisted (added without a pin) and none is missing (removed)."""
    on_disk = {
        p.name for p in SCRIPTS.iterdir()
        if p.is_file() and p.name != "CHECKSUMS.sha256"
    }
    pinned = set(_parse_manifest())
    assert on_disk == pinned, (
        f"scripts/ and CHECKSUMS.sha256 disagree — "
        f"unlisted: {on_disk - pinned}, stale: {pinned - on_disk}. "
        f"Re-review the change and regenerate the manifest."
    )


def test_every_script_matches_its_pin():
    for name, expected in _parse_manifest().items():
        digest = hashlib.sha256((SCRIPTS / name).read_bytes()).hexdigest()
        assert digest == expected, (
            f"{name} changed without updating CHECKSUMS.sha256 "
            f"(expected {expected[:16]}…, got {digest[:16]}…)"
        )


def test_nodesource_constant_agrees_with_manifest():
    """The dedicated NodeSource pin and the manifest must not drift apart."""
    assert _parse_manifest()["nodesource_setup_22.x.sh"] == cli._NODESOURCE_SETUP_SHA256


def test_in_code_pins_agree_with_manifest():
    """Manifest is the single source of truth; every in-code _SCRIPT_PINS anchor
    must match it. On mismatch the message shows the value to paste into cli.py —
    so maintaining a hash means: regenerate the manifest, run this test, update the
    named constant to what it prints."""
    pinned = _parse_manifest()
    for name, in_code in cli._SCRIPT_PINS.items():
        assert name in pinned, f"{name} pinned in code but absent from CHECKSUMS.sha256"
        assert in_code == pinned[name], (
            f"in-code pin for {name} is stale — update it in cli.py to: {pinned[name]}"
        )


def test_verify_helper_rejects_unknown_and_accepts_known():
    assert cli._verify_vendored_script("transcribe_xiaoyuzhou.sh") is True
    assert cli._verify_vendored_script("does-not-exist.sh") is False
