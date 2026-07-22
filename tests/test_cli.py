# -*- coding: utf-8 -*-
"""Tests for Agent Reach CLI."""

import shutil
import subprocess
from unittest.mock import patch

import pytest
import requests
import agent_reach.cli as cli
from agent_reach.cli import main


class TestOpenCLIInstall:
    def test_reprobe_after_install_is_fresh(self, capsys):
        """REG-1: the post-install re-probe must reset the memo, or a fast install
        reports the pre-install 'not installed' cached state as a failure."""
        from agent_reach.backends import OpenCLIStatus

        not_installed = OpenCLIStatus(installed=False)
        installed = OpenCLIStatus(installed=True, version="1.8.3", extension_installed=True)
        probes = iter([not_installed, installed])

        with patch("agent_reach.backends.opencli_status", side_effect=lambda *a, **k: next(probes)), \
             patch("agent_reach.backends.reset_opencli_status_cache") as reset, \
             patch("shutil.which", return_value="/usr/bin/npm"), \
             patch("subprocess.run"):
            cli._install_opencli_deps()

        out = capsys.readouterr().out
        assert "OpenCLI installed" in out
        assert "install failed" not in out
        reset.assert_called()  # memo cleared before the post-install probe


class TestCLI:
    def test_version(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            with patch("sys.argv", ["agent-reach", "version"]):
                main()
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "Agent Reach v" in captured.out

    def test_no_command_shows_help(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            with patch("sys.argv", ["agent-reach"]):
                main()
        assert exc_info.value.code == 0

    def test_doctor_runs(self, capsys):
        with patch("sys.argv", ["agent-reach", "doctor"]):
            main()
        captured = capsys.readouterr()
        assert "Agent Reach" in captured.out
        assert "✅" in captured.out

    def test_transcribe_command_prints_text(self, capsys):
        with patch("agent_reach.transcribe.transcribe", return_value="hello transcript"):
            with patch("sys.argv", ["agent-reach", "transcribe", "audio.mp3"]):
                main()
        captured = capsys.readouterr()
        assert "hello transcript" in captured.out

    def test_transcribe_command_writes_output_file(self, capsys, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)  # write target must be inside cwd (CR-009)
        with patch("agent_reach.transcribe.transcribe", return_value="saved text"):
            with patch("sys.argv", ["agent-reach", "transcribe", "audio.mp3", "-o", "t.txt"]):
                main()
        assert (tmp_path / "t.txt").read_text(encoding="utf-8").strip() == "saved text"
        assert "Transcript written" in capsys.readouterr().out

    def test_transcribe_refuses_output_outside_cwd(self, capsys, tmp_path, monkeypatch):
        """CR-009: an -o path outside cwd is refused (no arbitrary file write),
        but the transcript is still printed so the work isn't lost."""
        monkeypatch.chdir(tmp_path)
        outside = tmp_path.parent / "escape.txt"
        with patch("agent_reach.transcribe.transcribe", return_value="secret text"):
            with patch("sys.argv", ["agent-reach", "transcribe", "audio.mp3", "-o", str(outside)]):
                with pytest.raises(SystemExit) as ei:
                    main()
        assert ei.value.code != 0
        assert not outside.exists()
        out = capsys.readouterr().out
        assert "refusing to write outside" in out
        assert "secret text" in out  # transcript not lost

    @pytest.mark.parametrize("target", ["CLAUDE.md", ".git/hooks/pre-commit", "AGENTS.md"])
    def test_transcribe_refuses_instruction_and_dotfile_targets(
        self, capsys, tmp_path, monkeypatch, target
    ):
        """CR-010: a poisoned transcript must not be written over agent-instruction
        files or into dot-dirs (.git hooks, .claude, …)."""
        monkeypatch.chdir(tmp_path)
        with patch("agent_reach.transcribe.transcribe", return_value="poison"):
            with patch("sys.argv", ["agent-reach", "transcribe", "u", "-o", target]):
                with pytest.raises(SystemExit) as ei:
                    main()
        assert ei.value.code != 0
        assert not (tmp_path / target).exists()
        assert "refusing" in capsys.readouterr().out

    def test_transcribe_refuses_existing_without_force(self, capsys, tmp_path, monkeypatch):
        """CR-010: an existing -o target is not clobbered unless --force."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "out.txt").write_text("original", encoding="utf-8")
        with patch("agent_reach.transcribe.transcribe", return_value="new"):
            with patch("sys.argv", ["agent-reach", "transcribe", "u", "-o", "out.txt"]):
                with pytest.raises(SystemExit):
                    main()
        assert (tmp_path / "out.txt").read_text(encoding="utf-8") == "original"
        # With --force it overwrites.
        with patch("agent_reach.transcribe.transcribe", return_value="new"):
            with patch("sys.argv", ["agent-reach", "transcribe", "u", "-o", "out.txt", "--force"]):
                main()
        assert (tmp_path / "out.txt").read_text(encoding="utf-8").strip() == "new"

    def test_transcribe_local_file_requires_flag(self, capsys, tmp_path, monkeypatch):
        """REG-2: a local file source is refused unless --allow-local-file, and the
        flag is actually plumbed through to transcribe()."""
        monkeypatch.chdir(tmp_path)
        local = tmp_path / "audio.mp3"
        local.write_bytes(b"x")

        captured = {}

        def fake_transcribe(source, *, provider="auto", allow_local_file=False, **k):
            captured["allow_local_file"] = allow_local_file
            return "text"

        with patch("agent_reach.transcribe.transcribe", side_effect=fake_transcribe):
            with patch("sys.argv", ["agent-reach", "transcribe", str(local), "--allow-local-file"]):
                main()
        assert captured["allow_local_file"] is True

    def test_parse_twitter_cookie_input_separate_values(self):
        auth_token, ct0 = cli._parse_twitter_cookie_input("token123 ct0abc")
        assert auth_token == "token123"
        assert ct0 == "ct0abc"

    def test_parse_twitter_cookie_input_cookie_header(self):
        auth_token, ct0 = cli._parse_twitter_cookie_input(
            "auth_token=token123; ct0=ct0abc; other=value"
        )
        assert auth_token == "token123"
        assert ct0 == "ct0abc"

    def test_install_rdt_cli_prefers_github_source(self, monkeypatch, capsys):
        state = {"rdt_installed": False}
        commands = []

        def fake_which(name):
            if name == "rdt":
                return "/usr/local/bin/rdt" if state["rdt_installed"] else None
            if name == "pipx":
                return "/usr/local/bin/pipx"
            return None

        def fake_run(cmd, **kwargs):
            commands.append(cmd)
            state["rdt_installed"] = True
            return subprocess.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(shutil, "which", fake_which)
        monkeypatch.setattr(subprocess, "run", fake_run)

        cli._install_rdt_cli()

        out = capsys.readouterr().out
        assert commands == [["pipx", "install", cli._RDT_GIT_SOURCE]]
        assert "✅ rdt-cli installed" in out

    def test_install_reddit_deps_routes_by_environment(self, monkeypatch):
        """桌面 → OpenCLI;服务器 → rdt-cli(钉 git 源)。"""
        calls = []
        monkeypatch.setattr(cli, "_install_opencli_deps", lambda: calls.append("opencli"))
        monkeypatch.setattr(cli, "_install_rdt_cli", lambda: calls.append("rdt"))
        monkeypatch.setattr(shutil, "which", lambda _: None)

        monkeypatch.setattr(cli, "_detect_environment", lambda: "local")
        cli._install_reddit_deps()
        assert calls == ["opencli"]

        calls.clear()
        monkeypatch.setattr(cli, "_detect_environment", lambda: "server")
        cli._install_reddit_deps()
        assert calls == ["rdt"]


class TestCheckUpdateRetry:
    def test_retry_timeout_classification(self):
        sleeps = []

        def fake_sleep(seconds):
            sleeps.append(seconds)

        with patch("requests.get", side_effect=requests.exceptions.Timeout("timed out")):
            resp, err, attempts = cli._github_get_with_retry(
                "https://api.github.com/test",
                timeout=1,
                retries=3,
                sleeper=fake_sleep,
            )

        assert resp is None
        assert err == "timeout"
        assert attempts == 3
        assert sleeps == [1, 2]

    def test_retry_dns_classification(self):
        error = requests.exceptions.ConnectionError("getaddrinfo failed for api.github.com")
        with patch("requests.get", side_effect=error):
            resp, err, attempts = cli._github_get_with_retry(
                "https://api.github.com/test",
                retries=1,
                sleeper=lambda _x: None,
            )
        assert resp is None
        assert err == "dns"
        assert attempts == 1

    def test_retry_rate_limit_then_success(self):
        sleeps = []

        class R:
            def __init__(self, code, payload=None, headers=None):
                self.status_code = code
                self._payload = payload or {}
                self.headers = headers or {}

            def json(self):
                return self._payload

        sequence = [
            R(429, headers={"Retry-After": "3"}),
            R(200, payload={"tag_name": "v1.5.0"}),
        ]

        with patch("requests.get", side_effect=sequence):
            resp, err, attempts = cli._github_get_with_retry(
                "https://api.github.com/test",
                retries=3,
                sleeper=lambda s: sleeps.append(s),
            )

        assert err is None
        assert resp is not None
        assert resp.status_code == 200
        assert attempts == 2
        assert sleeps == [3.0]

    def test_classify_rate_limit_from_403(self):
        class R:
            status_code = 403
            headers = {"X-RateLimit-Remaining": "0"}

            @staticmethod
            def json():
                return {"message": "API rate limit exceeded"}

        assert cli._classify_github_response_error(R()) == "rate_limit"

    def test_check_update_reports_classified_error(self, capsys):
        with patch("agent_reach.cli._github_get_with_retry", return_value=(None, "timeout", 3)):
            result = cli._cmd_check_update()

        captured = capsys.readouterr()
        assert result == "error"
        assert "网络超时" in captured.out
        assert "已重试 3 次" in captured.out

    def test_check_update_survives_non_json_200(self, capsys):
        """CR-004: a captive portal returning HTTP 200 + HTML must not crash
        check-update — resp.json() raising ValueError degrades gracefully."""
        class R:
            status_code = 200
            headers = {}

            @staticmethod
            def json():
                raise ValueError("Expecting value: line 1 column 1 (char 0)")

        with patch("agent_reach.cli._github_get_with_retry", return_value=(R(), None, 1)):
            result = cli._cmd_check_update()

        captured = capsys.readouterr()
        assert result == "error"
        assert "响应格式异常" in captured.out


class TestVersionCompare:
    def test_newer_remote_triggers_update(self):
        assert cli._is_newer_version("1.5.0", "1.4.2") is True

    def test_equal_versions_no_update(self):
        assert cli._is_newer_version("1.5.0", "1.5.0") is False

    def test_local_ahead_of_release_no_downgrade_prompt(self):
        """发版窗口期本地装了 main(更新)时,不能提示"有更新"诱导降级。"""
        assert cli._is_newer_version("1.4.2", "1.5.0") is False

    def test_unparseable_falls_back_to_inequality(self):
        assert cli._is_newer_version("2026.06-beta", "1.5.0") is True
        assert cli._is_newer_version("1.5.0", "1.5.0-dev") is True


class TestWatchVersionCompare:
    def test_watch_does_not_prompt_downgrade(self, monkeypatch, capsys):
        """watch 与 check-update 同语义:本地领先远端 release 时不提示更新。"""
        class R:
            status_code = 200
            headers = {}

            @staticmethod
            def json():
                return {"tag_name": "v1.4.2", "body": ""}

        monkeypatch.setattr(cli, "_github_get_with_retry", lambda *a, **k: (R(), None, 1))
        monkeypatch.setattr(
            "agent_reach.doctor.check_all",
            lambda config: {"web": {"status": "ok", "name": "任意网页", "message": "ok",
                            "tier": 0, "backends": ["Jina Reader"], "active_backend": "Jina Reader"}},
        )
        cli._cmd_watch()
        out = capsys.readouterr().out
        assert "新版本可用" not in out
        assert "全部正常" in out
