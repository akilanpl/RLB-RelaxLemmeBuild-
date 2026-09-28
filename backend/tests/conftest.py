"""Default CI/unit tests must not consume external HTTP services."""
import os
import pytest
import httpx


@pytest.fixture(autouse=True)
def reject_external_http(monkeypatch):
    if os.environ.get('RLB_ALLOW_EXTERNAL_TESTS') == '1':
        return

    async def blocked_async(*args, **kwargs):
        raise AssertionError('External HTTP is disabled in local tests. Inject a MockTransport.')

    def blocked_sync(*args, **kwargs):
        raise AssertionError('External HTTP is disabled in local tests. Inject a MockTransport.')

    monkeypatch.setattr(httpx.AsyncHTTPTransport, 'handle_async_request', blocked_async)
    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', blocked_sync)
