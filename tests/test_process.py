from agent_reach.utils.process import mcporter_utf8_env_args, utf8_subprocess_env


def test_utf8_subprocess_env_forces_python_utf8():
    env = utf8_subprocess_env({"PYTHONUTF8": "0", "OTHER": "value"})

    assert env["PYTHONUTF8"] == "1"
    assert env["PYTHONIOENCODING"] == "utf-8"
    assert env["OTHER"] == "value"


def test_default_env_is_allowlisted_not_full_clone(monkeypatch):
    """CR-006: with no base, an exported secret must NOT reach the child env,
    while allowlisted system vars pass through."""
    monkeypatch.setenv("MY_UNRELATED_SECRET", "leak-me")
    monkeypatch.setenv("PATH", "/usr/bin")

    env = utf8_subprocess_env()

    assert "MY_UNRELATED_SECRET" not in env
    assert env["PATH"] == "/usr/bin"
    assert env["PYTHONUTF8"] == "1"


def test_credentials_not_in_default_env(monkeypatch):
    """CR-004: credentials must NOT be in the shared default env — they'd reach
    every probed CLI. They're injected per-probe via extra_env instead."""
    from agent_reach.utils.process import creds_from_env

    for name in ("GROQ_API_KEY", "TWITTER_AUTH_TOKEN", "TWITTER_CT0",
                 "AUTH_TOKEN", "CT0", "GH_TOKEN", "GITHUB_TOKEN"):
        monkeypatch.setenv(name, "secret")
    env = utf8_subprocess_env()
    for name in ("GROQ_API_KEY", "TWITTER_AUTH_TOKEN", "TWITTER_CT0",
                 "AUTH_TOKEN", "CT0", "GH_TOKEN", "GITHUB_TOKEN"):
        assert name not in env, f"{name} leaked into the shared default env"
    # creds_from_env picks only the requested, set ones.
    picked = creds_from_env("GH_TOKEN", "NOT_SET_VAR")
    assert picked == {"GH_TOKEN": "secret"}


def test_default_env_preserves_proxy_and_ca(monkeypatch):
    """CR-004: proxy + CA-bundle vars must reach probed children, or doctor runs
    proxyless on restricted networks and reports false timeouts."""
    monkeypatch.setenv("HTTP_PROXY", "http://p:8080")
    monkeypatch.setenv("HTTPS_PROXY", "http://p:8080")
    monkeypatch.setenv("NO_PROXY", "localhost")
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", "/etc/ca.pem")

    env = utf8_subprocess_env()

    assert env["HTTP_PROXY"] == "http://p:8080"
    assert env["HTTPS_PROXY"] == "http://p:8080"
    assert env["NO_PROXY"] == "localhost"
    assert env["REQUESTS_CA_BUNDLE"] == "/etc/ca.pem"


def test_mcporter_utf8_env_args():
    assert mcporter_utf8_env_args() == [
        "--env",
        "PYTHONUTF8=1",
        "--env",
        "PYTHONIOENCODING=utf-8",
    ]
