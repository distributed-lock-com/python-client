from __future__ import annotations

import os
from unittest import mock

import pytest

from distributed_lock import DEFAULT_CLUSTER, BadConfigurationError
from distributed_lock.common import (
    get_cluster,
    get_tenant_id,
    get_token,
)


@mock.patch.dict(os.environ, {"DLOCK_CLUSTER": "foo"}, clear=True)
def test_get_cluster():
    assert get_cluster() == "foo"


@mock.patch.dict(os.environ, {}, clear=True)
def test_get_cluster2():
    assert get_cluster() == DEFAULT_CLUSTER


@mock.patch.dict(os.environ, {"DLOCK_TOKEN": "foo"}, clear=True)
def test_get_token():
    assert get_token() == "foo"


@mock.patch.dict(os.environ, {}, clear=True)
def test_get_token2():
    with pytest.raises(BadConfigurationError):
        get_token()


@mock.patch.dict(os.environ, {"DLOCK_TENANT_ID": "foo"}, clear=True)
def test_get_tenant_id():
    assert get_tenant_id() == "foo"


@mock.patch.dict(os.environ, {}, clear=True)
def test_get_tenant_id2():
    with pytest.raises(BadConfigurationError):
        get_tenant_id()
