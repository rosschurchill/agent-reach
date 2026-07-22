# -*- coding: utf-8 -*-
"""FX-205 / AR-007: the Exa remote MCP (mcp.exa.ai) is opt-in — a default
install must NOT register the egress; requesting the exa channel must.
Also FX-204 / AR-005: the get_status tool description discloses live egress."""

import pathlib
from unittest.mock import patch

from agent_reach import cli


def _run_install_mcporter(configure_exa):
    """Call _install_mcporter with mcporter present, capturing mcporter argv."""
    calls = []

    def fake_run(cmd, *a, **k):
        calls.append(cmd)

        class R:
            stdout = ""  # mcporter config list -> empty (exa not yet added)
        return R()

    with patch("shutil.which", return_value="/usr/bin/mcporter"), patch(
        "subprocess.run", side_effect=fake_run
    ):
        cli._install_mcporter(configure_exa=configure_exa)
    return calls


def _added_exa(calls):
    return any(
        c[:3] == ["mcporter", "config", "add"] and "exa" in c for c in calls
    )


def test_default_install_does_not_configure_exa():
    calls = _run_install_mcporter(configure_exa=False)
    assert not _added_exa(calls), "default install must not register exa egress"


def test_opt_in_configures_exa():
    calls = _run_install_mcporter(configure_exa=True)
    assert _added_exa(calls), "explicit exa/search request should configure exa"


def test_mcporter_json_has_no_default_exa_egress():
    import json

    cfg = json.loads(
        pathlib.Path("config/mcporter.json").read_text(encoding="utf-8")
    )
    assert "exa" not in cfg.get("mcpServers", {})


def test_get_status_description_discloses_egress():
    src = pathlib.Path("agent_reach/integrations/mcp_server.py").read_text(
        encoding="utf-8"
    )
    # The get_status tool must warn that it makes outbound network calls.
    assert "outbound network" in src
