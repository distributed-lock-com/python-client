# python-client

[![GitHub Workflow Status](https://img.shields.io/github/actions/workflow/status/distributed-lock-com/python-client/ci.yaml)](https://github.com/distributed-lock-com/python-client/actions/workflows/ci.yaml)
[![Codecov](https://img.shields.io/codecov/c/github/distributed-lock-com/python-client)](https://app.codecov.io/github/distributed-lock-com/python-client)
[![pypi badge](https://img.shields.io/pypi/v/python-client?color=brightgreen)](https://pypi.org/project/python-client/)


## What is it?

This is a Python (3.7+) client library for https://distributed-lock.com SAAS.

> **Note**
> The asyncio support is planned but not here for the moment 🤷‍♂️

## What is it not?

It's not a CLI (just a library). If you are looking for a good CLI binary, have a look at
[our golang client](https://github.com/distributed-lock-com/go-client).

## How to use it?

### Install

```
pip install distributed-lock-client
```

### Quickstart

```python
from distributed_lock_client import DistributedLockClient

# assert DLOCK_TOKEN env var defined with your API token
# assert DLOCK_TENANT_ID env var defined with your "tenant id"
# (you can also pass them to the DistributedLockClient
#  constructor or you can also use DLOCK_CLUSTER env var)

with DistributedLockClient(cluster="europe-free").exclusive_lock(
    "bar", lifetime=20, wait=10
):
    # WE HAVE THE LOCK!
    # [...] DOING SOME IMPORTANT THINGS [...]
    pass

# THE LOCK IS RELEASED
```

### Usage

You have 2 APIs: 

- the (recommended) context manager API (like above)
- the low level API

For the low level API, the idea is the same:

- first, you create a `DistributedLockClient` object with some options (most of them can be set as env var)
- second, you invoke on the object the method `acquire_exclusive_lock()` and/or `release_exclusive_lock`

Example (of the low level API):

```python
from distributed_lock_client import DistributedLockClient

# assert DLOCK_TOKEN env var defined with your API token
# assert DLOCK_TENANT_ID env var defined with your "tenant id"
# (you can also pass them to the DistributedLockClient
#  constructor or you can also use DLOCK_CLUSTER env var)
client = DistributedLockClient(cluster="europe-free")

# Acquire the resource "bar"
acquired_resource = client.acquire_exclusive_lock("bar", lifetime=20, wait=10)

lock_id = acquired_resource.lock_id
# WE HAVE THE LOCK!
# [...] DOING SOME IMPORTANT THINGS [...]

# Release the resource "bar"
client.release_exclusive_lock("bar", lock_id)
```

### API reference

https://distributed-lock-com.github.io/python-client/

## Hacking

- managed by [Poetry](https://python-poetry.org/)
- linting: `make lint` (inside a Poetry shell)
- unit testing: `make test` (inside a Poetry shell)
- api doc: `make apidoc` (inside a Poetry shell)