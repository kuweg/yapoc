"""Pytest configuration shared by the whole suite.

## Why this file exists

22 of the suite's tests were failing with `401 Unauthorized` against every API
endpoint. The cause is not a bug in the app: `AccessMiddleware` (app/backend/
access.py) allows unauthenticated requests only when `backend_api_token` is
unset AND the request is loopback-to-loopback. Starlette's `TestClient`
identifies itself as client `testclient` on host `testserver`, neither of which
is a loopback address, so every request was correctly refused.

Patching the default here rather than in each test module is deliberate: the
clients are constructed at module import time (`client = TestClient(app)`), so a
fixture would run too late to affect them. pytest imports conftest.py before it
collects test modules, which is early enough.

This grants tests exactly the trust the middleware already extends to a local
developer — it does not disable the auth check. A test that sets
`backend_api_token` still exercises the token path normally.
"""

from __future__ import annotations

import starlette.testclient as _testclient

_LOOPBACK_BASE_URL = "http://127.0.0.1"
_LOOPBACK_CLIENT = ("127.0.0.1", 50000)

_original_init = _testclient.TestClient.__init__


def _loopback_init(self, app, *args, **kwargs):
    """Default TestClient to a loopback identity, honouring explicit overrides."""
    if kwargs.get("base_url", "http://testserver") == "http://testserver":
        kwargs["base_url"] = _LOOPBACK_BASE_URL
    kwargs.setdefault("client", _LOOPBACK_CLIENT)
    return _original_init(self, app, *args, **kwargs)


if getattr(_testclient.TestClient.__init__, "__name__", "") != "_loopback_init":
    _testclient.TestClient.__init__ = _loopback_init
