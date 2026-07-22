from agent_reach.utils.process import mcporter_utf8_env_args, utf8_subprocess_env


def test_utf8_subprocess_env_forces_python_utf8():
    env = utf8_subprocess_env({"PYTHONUTF8": "0", "OTHER": "value"})

    assert env["PYTHONUTF8"] == "1"
    assert env["PYTHONIOENCODING"] == "utf-8"
    assert env["OTHER"] == "value"


def test_default_env_is_allowlisted_not_full_clone(monkeypatch):
    """CR-006: with no base, an exported secret must NOT reach the child env,
    while allowlisted vars (PATH + creds the CLIs read) pass through."""
    monkeypatch.setenv("MY_UNRELATED_SECRET", "leak-me")
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")

    env = utf8_subprocess_env()

    assert "MY_UNRELATED_SECRET" not in env
    assert env["PATH"] == "/usr/bin"
    assert env["GROQ_API_KEY"] == "gsk_test"
    assert env["PYTHONUTF8"] == "1"


def test_mcporter_utf8_env_args():
    assert mcporter_utf8_env_args() == [
        "--env",
        "PYTHONUTF8=1",
        "--env",
        "PYTHONIOENCODING=utf-8",
    ]
