# -*- coding: utf-8 -*-
"""Tests for agent_reach.transcribe — provider routing, fallback, and errors."""

import socket
from typing import List

import pytest

from agent_reach import transcribe as tr
from agent_reach.config import Config

# --- Fixtures ----------------------------------------------------------- #


@pytest.fixture
def fake_config(tmp_path, monkeypatch):
    """A Config that writes to a temp dir and never touches the user's HOME."""
    cfg_path = tmp_path / "config.yaml"
    monkeypatch.setattr(Config, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(Config, "CONFIG_FILE", cfg_path)
    cfg = Config(config_path=cfg_path)
    return cfg


@pytest.fixture
def chunk_file(tmp_path):
    p = tmp_path / "chunk.m4a"
    p.write_bytes(b"\x00fake-m4a-bytes")
    return p


class FakeResponse:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300


# --- transcribe_chunk: provider routing -------------------------------- #


class TestTranscribeChunk:
    def test_routes_to_groq_endpoint(self, monkeypatch, fake_config, chunk_file):
        fake_config.set("groq_api_key", "gsk_test")
        captured = {}

        def fake_post(url, headers=None, files=None, data=None, timeout=None):
            captured["url"] = url
            captured["headers"] = headers
            captured["model"] = data["model"]
            return FakeResponse(200, "hello world")

        monkeypatch.setattr(tr.requests, "post", fake_post)
        text = tr.transcribe_chunk(chunk_file, "groq", config=fake_config)
        assert text == "hello world"
        assert captured["url"] == tr.PROVIDERS["groq"]["endpoint"]
        assert captured["model"] == "whisper-large-v3"
        assert captured["headers"]["Authorization"] == "Bearer gsk_test"

    def test_routes_to_openai_endpoint(self, monkeypatch, fake_config, chunk_file):
        fake_config.set("openai_api_key", "sk-test")
        captured = {}

        def fake_post(url, headers=None, files=None, data=None, timeout=None):
            captured["url"] = url
            captured["model"] = data["model"]
            return FakeResponse(200, "openai output")

        monkeypatch.setattr(tr.requests, "post", fake_post)
        text = tr.transcribe_chunk(chunk_file, "openai", config=fake_config)
        assert text == "openai output"
        assert captured["url"] == tr.PROVIDERS["openai"]["endpoint"]
        assert captured["model"] == "whisper-1"

    def test_raises_when_key_missing(self, fake_config, chunk_file):
        with pytest.raises(tr.NoProviderConfigured):
            tr.transcribe_chunk(chunk_file, "groq", config=fake_config)

    def test_raises_on_http_error(self, monkeypatch, fake_config, chunk_file):
        fake_config.set("groq_api_key", "gsk_test")
        monkeypatch.setattr(
            tr.requests,
            "post",
            lambda *a, **k: FakeResponse(429, "rate limited"),
        )
        with pytest.raises(tr.TranscribeError, match="HTTP 429"):
            tr.transcribe_chunk(chunk_file, "groq", config=fake_config)

    def test_unknown_provider(self, fake_config, chunk_file):
        with pytest.raises(tr.TranscribeError, match="unknown provider"):
            tr.transcribe_chunk(chunk_file, "azure", config=fake_config)


# --- _transcribe_with_fallback ----------------------------------------- #


class TestFallback:
    def test_groq_succeeds_no_openai_call(self, monkeypatch, fake_config, chunk_file):
        fake_config.set("groq_api_key", "gsk_test")
        fake_config.set("openai_api_key", "sk-test")
        calls: List[str] = []

        def fake_post(url, headers=None, files=None, data=None, timeout=None):
            calls.append(url)
            return FakeResponse(200, "from-groq")

        monkeypatch.setattr(tr.requests, "post", fake_post)
        text = tr._transcribe_with_fallback(chunk_file, ["groq", "openai"], fake_config)
        assert text == "from-groq"
        assert calls == [tr.PROVIDERS["groq"]["endpoint"]]

    def test_groq_429_falls_back_to_openai(self, monkeypatch, fake_config, chunk_file):
        fake_config.set("groq_api_key", "gsk_test")
        fake_config.set("openai_api_key", "sk-test")
        calls: List[str] = []

        def fake_post(url, headers=None, files=None, data=None, timeout=None):
            calls.append(url)
            if url == tr.PROVIDERS["groq"]["endpoint"]:
                return FakeResponse(429, "rate limited")
            return FakeResponse(200, "from-openai")

        monkeypatch.setattr(tr.requests, "post", fake_post)
        text = tr._transcribe_with_fallback(chunk_file, ["groq", "openai"], fake_config)
        assert text == "from-openai"
        assert calls == [
            tr.PROVIDERS["groq"]["endpoint"],
            tr.PROVIDERS["openai"]["endpoint"],
        ]

    def test_skip_unconfigured_provider(self, monkeypatch, fake_config, chunk_file):
        # Only openai key configured — fallback should skip groq silently.
        fake_config.set("openai_api_key", "sk-test")
        calls: List[str] = []

        def fake_post(url, headers=None, files=None, data=None, timeout=None):
            calls.append(url)
            return FakeResponse(200, "via-openai")

        monkeypatch.setattr(tr.requests, "post", fake_post)
        text = tr._transcribe_with_fallback(chunk_file, ["groq", "openai"], fake_config)
        assert text == "via-openai"
        assert calls == [tr.PROVIDERS["openai"]["endpoint"]]

    def test_all_fail_raises_with_last_error(self, monkeypatch, fake_config, chunk_file):
        fake_config.set("groq_api_key", "gsk_test")
        fake_config.set("openai_api_key", "sk-test")
        monkeypatch.setattr(
            tr.requests,
            "post",
            lambda *a, **k: FakeResponse(500, "boom"),
        )
        with pytest.raises(tr.TranscribeError, match="all providers failed"):
            tr._transcribe_with_fallback(chunk_file, ["groq", "openai"], fake_config)


# --- transcribe (orchestrator) ---------------------------------------- #


class TestOrchestrator:
    def test_local_file_skips_yt_dlp(self, monkeypatch, fake_config, tmp_path, chunk_file):
        fake_config.set("groq_api_key", "gsk_test")

        def boom_download(*a, **k):
            raise AssertionError("yt-dlp must not be called for local files")

        # Stub heavy external steps to no-ops that keep file paths valid.
        compressed = tmp_path / "compressed.m4a"
        compressed.write_bytes(b"x" * 1024)

        def fake_compress(src, out_dir):
            return compressed

        monkeypatch.setattr(tr, "download_audio", boom_download)
        monkeypatch.setattr(tr, "compress_audio", fake_compress)
        monkeypatch.setattr(
            tr.requests,
            "post",
            lambda *a, **k: FakeResponse(200, "transcript text"),
        )

        text = tr.transcribe(
            str(chunk_file),
            out_dir=tmp_path / "work",
            config=fake_config,
            allow_local_file=True,
        )
        assert text == "transcript text"

    def test_chunks_concatenated_with_newlines(
        self, monkeypatch, fake_config, tmp_path, chunk_file
    ):
        fake_config.set("groq_api_key", "gsk_test")
        # Force the "needs chunking" path by writing a file above the size limit.
        big = tmp_path / "compressed.m4a"
        big.write_bytes(b"x" * (tr.SIZE_LIMIT_BYTES + 1))
        monkeypatch.setattr(tr, "compress_audio", lambda src, out_dir: big)
        c1 = tmp_path / "chunk_001.m4a"
        c2 = tmp_path / "chunk_002.m4a"
        c1.write_bytes(b"a")
        c2.write_bytes(b"b")
        monkeypatch.setattr(tr, "chunk_audio", lambda src, out_dir: [c1, c2])

        responses = iter(["part one ", "part two "])
        monkeypatch.setattr(
            tr.requests,
            "post",
            lambda *a, **k: FakeResponse(200, next(responses)),
        )

        text = tr.transcribe(
            str(chunk_file),
            out_dir=tmp_path / "work",
            config=fake_config,
            allow_local_file=True,
        )
        assert text == "part one\npart two"

    def test_no_provider_configured_fails_fast(self, fake_config, chunk_file):
        with pytest.raises(tr.NoProviderConfigured):
            tr.transcribe(str(chunk_file), config=fake_config)

    def test_chunk_failure_attaches_partial_transcript(
        self, monkeypatch, fake_config, tmp_path, chunk_file
    ):
        """CR-009: if a later chunk fails, the completed chunks are attached to
        the error (err.partial) so the paid work isn't discarded."""
        fake_config.set("groq_api_key", "gsk_test")
        big = tmp_path / "compressed.m4a"
        big.write_bytes(b"x" * (tr.SIZE_LIMIT_BYTES + 1))
        monkeypatch.setattr(tr, "compress_audio", lambda src, out_dir: big)
        c1, c2 = tmp_path / "c1.m4a", tmp_path / "c2.m4a"
        c1.write_bytes(b"a")
        c2.write_bytes(b"b")
        monkeypatch.setattr(tr, "chunk_audio", lambda src, out_dir: [c1, c2])

        def fallback(chunk, order, config):
            if chunk == c1:
                return "chunk one "
            raise tr.TranscribeError("provider 5xx on chunk 2")

        monkeypatch.setattr(tr, "_transcribe_with_fallback", fallback)

        with pytest.raises(tr.TranscribeError) as ei:
            tr.transcribe(
                str(chunk_file), out_dir=tmp_path / "w",
                config=fake_config, allow_local_file=True,
            )
        assert getattr(ei.value, "partial", "") == "chunk one"
        assert ei.value.failed_chunk == 2

    def test_local_file_refused_without_optin(self, fake_config, chunk_file, tmp_path):
        """CR-005: a local path is refused unless allow_local_file=True, so a
        path-shaped string can't bypass the download URL guard."""
        fake_config.set("groq_api_key", "gsk_test")
        with pytest.raises(tr.TranscribeError, match="allow_local_file"):
            tr.transcribe(
                str(chunk_file), out_dir=tmp_path / "w", config=fake_config
            )


class TestDownloadUrlGuard:
    """CR-007/008: best-effort SSRF pre-check on the yt-dlp download path.
    DNS is mocked (CR-010) so the suite is deterministic offline."""

    @staticmethod
    def _patch_dns(monkeypatch, host, ip):
        family = socket.AF_INET6 if ":" in ip else socket.AF_INET
        sockaddr = (ip, 0, 0, 0) if ":" in ip else (ip, 0)

        def fake_gai(h, *a, **k):
            if h != host:
                raise socket.gaierror(f"NXDOMAIN {h}")
            return [(family, socket.SOCK_STREAM, 0, "", sockaddr)]

        monkeypatch.setattr(tr.socket, "getaddrinfo", fake_gai)

    @pytest.mark.parametrize(
        "ip",
        [
            "127.0.0.1",            # loopback
            "169.254.169.254",      # cloud metadata / link-local
            "10.0.0.5",             # private
            "100.64.0.1",           # CGNAT / Tailscale — is_private False (CR-007)
            "::ffff:127.0.0.1",     # IPv4-mapped loopback (CR-008)
            "::ffff:169.254.169.254",
        ],
    )
    def test_private_resolution_rejected(self, monkeypatch, ip):
        # Ensure no proxy/allowlist env interferes with the resolution path.
        for v in ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY",
                  "AGENT_REACH_TRANSCRIBE_ALLOWED_HOSTS"):
            monkeypatch.delenv(v, raising=False)
        self._patch_dns(monkeypatch, "evil.test", ip)
        with pytest.raises(tr.TranscribeError):
            tr._assert_safe_public_url("http://evil.test/x")

    def test_allowlist_env_is_authoritative(self, monkeypatch):
        """CR-008: a host in AGENT_REACH_TRANSCRIBE_ALLOWED_HOSTS is allowed
        without resolution; one not in it is refused."""
        monkeypatch.setenv("AGENT_REACH_TRANSCRIBE_ALLOWED_HOSTS", "example.com, cdn.test")
        # Would resolve to loopback, but the allowlist short-circuits before DNS:
        self._patch_dns(monkeypatch, "media.example.com", "127.0.0.1")
        tr._assert_safe_public_url("https://media.example.com/a.mp3")  # suffix match, allowed
        with pytest.raises(tr.TranscribeError):
            tr._assert_safe_public_url("https://evil.test/a.mp3")

    def test_proxy_skips_local_resolution(self, monkeypatch):
        """REG-6: behind a proxy, the local IP pre-check is skipped (split-DNS /
        proxy-only networks would otherwise false-reject valid URLs)."""
        monkeypatch.delenv("AGENT_REACH_TRANSCRIBE_ALLOWED_HOSTS", raising=False)
        monkeypatch.setenv("HTTPS_PROXY", "http://proxy:8080")
        # Even if it would resolve to a private IP under split-DNS, proxy path allows.
        self._patch_dns(monkeypatch, "cdn.corp", "10.1.2.3")
        tr._assert_safe_public_url("https://cdn.corp/a.mp3")  # must not raise

    @pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://x/a.mp3", "not-a-url"])
    def test_bad_scheme_rejected(self, url):
        with pytest.raises(tr.TranscribeError):
            tr._assert_safe_public_url(url)

    def test_public_resolution_allowed(self, monkeypatch):
        self._patch_dns(monkeypatch, "ok.test", "93.184.216.34")
        tr._assert_safe_public_url("https://ok.test/a.mp3")  # must not raise

    def test_empty_resolution_rejected(self, monkeypatch):
        monkeypatch.setattr(tr.socket, "getaddrinfo", lambda *a, **k: [])
        with pytest.raises(tr.TranscribeError):
            tr._assert_safe_public_url("http://weird.test/x")

    def test_nxdomain_rejected(self, monkeypatch):
        def boom(*a, **k):
            raise socket.gaierror("nope")

        monkeypatch.setattr(tr.socket, "getaddrinfo", boom)
        with pytest.raises(tr.TranscribeError):
            tr._assert_safe_public_url("http://nx.test/x")

    def test_invalid_provider_string(self, fake_config, chunk_file):
        with pytest.raises(tr.TranscribeError, match="unknown provider"):
            tr.transcribe(str(chunk_file), provider="azure", config=fake_config)


# --- YouTubeChannel integration --------------------------------------- #


class TestYouTubeChannelTranscribe:
    def test_delegates_to_transcribe(self, monkeypatch, fake_config):
        from agent_reach.channels.youtube import YouTubeChannel

        captured = {}

        def fake_transcribe(source, *, provider="auto", out_dir=None, config=None):
            captured["source"] = source
            captured["provider"] = provider
            captured["config"] = config
            return "delegated text"

        monkeypatch.setattr(tr, "transcribe", fake_transcribe)
        out = YouTubeChannel().transcribe(
            "https://youtu.be/abc", provider="groq", config=fake_config
        )
        assert out == "delegated text"
        assert captured["source"] == "https://youtu.be/abc"
        assert captured["provider"] == "groq"
        assert captured["config"] is fake_config


# --- Config feature requirement --------------------------------------- #


class TestConfigOpenAIWhisper:
    def test_openai_whisper_feature_registered(self, fake_config):
        assert "openai_whisper" in Config.FEATURE_REQUIREMENTS
        assert Config.FEATURE_REQUIREMENTS["openai_whisper"] == ["openai_api_key"]
        assert not fake_config.is_configured("openai_whisper")
        fake_config.set("openai_api_key", "sk-test")
        assert fake_config.is_configured("openai_whisper")
