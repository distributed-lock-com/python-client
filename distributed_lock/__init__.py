from __future__ import annotations

from distributed_lock.common import AcquiredRessource
from distributed_lock.const import (
    DEFAULT_CLUSTER,
    DEFAULT_LIFETIME,
    DEFAULT_SERVER_SIDE_WAIT,
)
from distributed_lock.exception import (
    BadConfigurationError,
    NotAcquiredError,
    NotAcquiredException,
    NotReleasedError,
)
from distributed_lock.sync import DistributedLockClient

__all__ = [
    "DEFAULT_CLUSTER",
    "DEFAULT_LIFETIME",
    "DEFAULT_SERVER_SIDE_WAIT",
    "AcquiredRessource",
    "DistributedLockClient",
    "NotAcquiredError",
    "NotReleasedError",
    "NotAcquiredException",
    "BadConfigurationError",
]

__pdoc__ = {"sync": False, "exception": False, "common": False}

VERSION = "v0.0.0"
