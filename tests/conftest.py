"""Keep application tests independent of services and private credentials."""

import socket

import pytest


@pytest.fixture(autouse=True)
def prohibit_network(monkeypatch):
    """Fail immediately if a test tries to contact any external service."""

    def reject_connection(*_args, **_kwargs):
        raise AssertionError("Offline tests must mock network connections")

    monkeypatch.setattr(socket.socket, "connect", reject_connection)
    monkeypatch.setattr(socket.socket, "connect_ex", reject_connection)
