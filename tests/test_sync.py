from __future__ import annotations

import json
import os
from unittest import mock

import httpx
import pytest

from distributed_lock import (
    DEFAULT_LIFETIME,
    DEFAULT_WAIT,
    AcquiredRessource,
    DistributedLockClient,
    NotAcquiredException,
    NotReleasedError,
)

MOCKED_ENVIRON = {
    "DLOCK_CLUSTER": "cluster",
    "DLOCK_TENANT_ID": "tenant_id",
    "DLOCK_TOKEN": "token",
}
AR = AcquiredRessource(
    lock_id="1234",
    resource="bar",
    tenant_id="tenant_id",
    user_agent="foo/1.0",
    user_data={"foo": "bar"},
)


@mock.patch.dict(os.environ, MOCKED_ENVIRON, clear=True)
def test_resource_url():
    x = DistributedLockClient()
    assert (
        x.get_resource_url("bar")
        == "https://cluster.distributed-lock.com/exclusive_locks/tenant_id/bar"
    )


@mock.patch.dict(os.environ, MOCKED_ENVIRON, clear=True)
@pytest.mark.respx(base_url="https://cluster.distributed-lock.com")
def test_acquire(respx_mock):
    respx_mock.post("/exclusive_locks/tenant_id/bar").mock(
        return_value=httpx.Response(201, json=AR.to_dict())
    )
    x = DistributedLockClient()
    ar = x.acquire_exclusive_lock("bar")
    assert len(respx_mock.calls) == 1
    body = json.loads(respx_mock.calls.last.request.content.decode("utf8"))
    assert body["wait"] == DEFAULT_WAIT
    assert body["lifetime"] == DEFAULT_LIFETIME
    headers = respx_mock.calls.last.request.headers
    assert headers["host"] == "cluster.distributed-lock.com"
    assert headers["authorization"] == "Bearer token"
    assert headers["content-type"] == "application/json"
    assert ar is not None
    assert ar.lock_id == AR.lock_id
    assert ar.resource == AR.resource
    assert ar.tenant_id == AR.tenant_id
    assert ar.created.isoformat()[0:19] == AR.created.isoformat()[0:19]
    assert ar.expires.isoformat()[0:19] == AR.expires.isoformat()[0:19]
    assert ar.user_agent == AR.user_agent
    assert ar.user_data == AR.user_data


@mock.patch.dict(os.environ, MOCKED_ENVIRON, clear=True)
@pytest.mark.respx(base_url="https://cluster.distributed-lock.com")
def test_not_acquired(respx_mock):
    respx_mock.post("/exclusive_locks/tenant_id/bar").mock(
        return_value=httpx.Response(409)
    )
    x = DistributedLockClient()
    with pytest.raises(NotAcquiredException):
        x.acquire_exclusive_lock("bar", wait=3)
    assert len(respx_mock.calls) > 1


@mock.patch.dict(os.environ, MOCKED_ENVIRON, clear=True)
@pytest.mark.respx(base_url="https://cluster.distributed-lock.com")
def test_release(respx_mock):
    respx_mock.delete("/exclusive_locks/tenant_id/bar/1234").mock(
        return_value=httpx.Response(204)
    )
    x = DistributedLockClient()
    x.release_exclusive_lock("bar", "1234")
    assert len(respx_mock.calls) == 1
    headers = respx_mock.calls.last.request.headers
    assert headers["host"] == "cluster.distributed-lock.com"
    assert headers["authorization"] == "Bearer token"


@mock.patch.dict(os.environ, MOCKED_ENVIRON, clear=True)
@pytest.mark.respx(base_url="https://cluster.distributed-lock.com")
def test_not_released(respx_mock):
    respx_mock.delete("/exclusive_locks/tenant_id/bar/1234").mock(
        return_value=httpx.Response(500)
    )
    x = DistributedLockClient()
    with pytest.raises(NotReleasedError):
        x.release_exclusive_lock("bar", lock_id="1234", wait=3)
    assert len(respx_mock.calls) > 1
    headers = respx_mock.calls.last.request.headers
    assert headers["host"] == "cluster.distributed-lock.com"
    assert headers["authorization"] == "Bearer token"


@mock.patch.dict(os.environ, MOCKED_ENVIRON, clear=True)
@pytest.mark.respx(base_url="https://cluster.distributed-lock.com")
def test_context_manager(respx_mock):
    respx_mock.post("/exclusive_locks/tenant_id/bar").mock(
        return_value=httpx.Response(201, json=AR.to_dict())
    )
    respx_mock.delete("/exclusive_locks/tenant_id/bar/1234").mock(
        return_value=httpx.Response(204)
    )
    x = DistributedLockClient()
    with x.exclusive_lock("bar"):
        pass
    assert len(respx_mock.calls) == 2
