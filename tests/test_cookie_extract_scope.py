# -*- coding: utf-8 -*-
"""FX-202 / AR-003: extract_all() must capture only the named auth/session
cookies per platform, not every cookie that happens to share the domain."""

import sys
import types

import pytest

from agent_reach import cookie_extract


def _fake_rookiepy(cookies):
    """A stand-in rookiepy module whose every browser fn returns `cookies`."""
    mod = types.SimpleNamespace()
    for browser in ("chrome", "firefox", "edge", "brave", "opera"):
        setattr(mod, browser, lambda c=cookies: c)
    return mod


@pytest.fixture
def mixed_jar(monkeypatch):
    cookies = [
        # XHS: two allowlisted + one pure-analytics that must be dropped.
        {"name": "web_session", "value": "S", "domain": ".xiaohongshu.com"},
        {"name": "a1", "value": "A", "domain": ".xiaohongshu.com"},
        {"name": "_ga", "value": "TRACK", "domain": ".xiaohongshu.com"},
        # Xueqiu: auth token + an analytics cookie that must be dropped.
        {"name": "xq_a_token", "value": "T", "domain": ".xueqiu.com"},
        {"name": "Hm_lvt_9", "value": "TRACK", "domain": ".xueqiu.com"},
        # Twitter: unchanged named-dict path.
        {"name": "auth_token", "value": "AT", "domain": ".x.com"},
        {"name": "ct0", "value": "C0", "domain": ".x.com"},
    ]
    monkeypatch.setitem(sys.modules, "rookiepy", _fake_rookiepy(cookies))
    return cookies


def test_xhs_drops_non_allowlisted_cookies(mixed_jar):
    out = cookie_extract.extract_all("chrome")
    xhs = out["xhs"]["cookie_string"]
    assert "web_session=S" in xhs
    assert "a1=A" in xhs
    assert "_ga" not in xhs  # analytics cookie must not be collected


def test_xueqiu_drops_non_allowlisted_cookies(mixed_jar):
    out = cookie_extract.extract_all("chrome")
    xq = out["xueqiu"]["cookie_string"]
    assert "xq_a_token=T" in xq
    assert "Hm_lvt" not in xq


def test_twitter_named_dict_path_unchanged(mixed_jar):
    out = cookie_extract.extract_all("chrome")
    assert out["twitter"] == {"auth_token": "AT", "ct0": "C0"}


def test_no_grab_all_none_spec_remains():
    for spec in cookie_extract.PLATFORM_SPECS:
        assert spec["cookies"] is not None, f"{spec['name']} still grabs all cookies"
