from __future__ import annotations

import urllib.request

import desktop_launcher


def test_merge_no_proxy_value_preserves_existing_entries_and_adds_localhost() -> None:
    value = desktop_launcher.merge_no_proxy_value("example.com, 10.0.0.0/8,localhost")

    assert value.split(",") == ["example.com", "10.0.0.0/8", "localhost", "127.0.0.1"]


def test_ensure_localhost_no_proxy_updates_both_environment_keys() -> None:
    env = {"NO_PROXY": "example.com", "no_proxy": "internal.local,127.0.0.1"}

    desktop_launcher.ensure_localhost_no_proxy(env)

    assert env["NO_PROXY"] == "example.com,127.0.0.1,localhost"
    assert env["no_proxy"] == "internal.local,127.0.0.1,localhost"


def test_healthcheck_opener_disables_proxy_handlers() -> None:
    opener = desktop_launcher.create_localhost_healthcheck_opener()

    assert not any(isinstance(handler, urllib.request.ProxyHandler) for handler in opener.handlers)
