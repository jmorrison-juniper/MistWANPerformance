"""Tests for the wsgi.py entry point."""

import importlib
import sys

import run_dashboard


def test_wsgi_server_is_built_by_run_dashboard(monkeypatch):
    """wsgi.server must be the app that run_dashboard.create_wsgi_app() builds."""
    built_app = object()
    calls = []

    def fake_create_wsgi_app():
        calls.append(True)
        return built_app

    monkeypatch.setattr(run_dashboard, "create_wsgi_app", fake_create_wsgi_app)
    sys.modules.pop("wsgi", None)
    try:
        wsgi = importlib.import_module("wsgi")
        assert wsgi.server is built_app
        assert calls == [True]
    finally:
        sys.modules.pop("wsgi", None)