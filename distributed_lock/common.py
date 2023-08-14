from __future__ import annotations

import datetime
import os
from dataclasses import asdict, dataclass, field
from typing import Any

from distributed_lock.const import DEFAULT_CLUSTER
from distributed_lock.exception import BadConfigurationError, DistributedLockError


@dataclass
class AcquiredRessource:
    """This dataclass holds an acquired ressource."""

    resource: str
    """The resource name."""

    lock_id: str
    """The lock unique identifier (you will need it to unlock)."""

    tenant_id: str
    """The tenant identifier."""

    created: datetime.datetime = field(default_factory=datetime.datetime.utcnow)
    """The lock creation datetime."""

    expires: datetime.datetime = field(default_factory=datetime.datetime.utcnow)
    """The lock expiration datetime."""

    user_agent: str = ""
    """Your user-agent (warning: not supported in all plans)."""

    user_data: Any = ""
    """User data stored with the lock (warning: not supported in all plans)."""

    @classmethod
    def from_dict(cls, d: dict) -> AcquiredRessource:
        """Create an AcquiredRessource from a dict."""
        for f in (
            "lock_id",
            "resource",
            "tenant_id",
            "created",
            "expires",
            "user_agent",
            "user_data",
        ):
            if f not in d:
                raise DistributedLockError(f"bad reply from service, missing {f}")
        d2 = dict(d)
        for f in ("created", "expires"):
            if isinstance(d2[f], str):
                # Python < 3.9 has weird support of the "Z" suffix => let's replace by "+00:00"
                d2[f] = datetime.datetime.fromisoformat(d2[f].replace("Z", "+00:00"))
        return cls(**d2)

    def to_dict(self) -> dict:
        """Convert an AcquiredRessource to a dict."""
        d = asdict(self)
        for f in ("created", "expires"):
            d[f] = d[f].isoformat()[0:19] + "Z"
        return d


def get_cluster() -> str:
    """Get the target cluster from env or from default."""
    if os.environ.get("DLOCK_CLUSTER"):
        return os.environ["DLOCK_CLUSTER"].lower().strip()
    return DEFAULT_CLUSTER


def get_token() -> str:
    """Get the service token from env (raise an exception if not set).

    Raises:
        BadConfigurationError: if the token is not set.
    """
    if os.environ.get("DLOCK_TOKEN"):
        return os.environ["DLOCK_TOKEN"].lower().strip()
    raise BadConfigurationError("You must provide a token (or set DLOCK_TOKEN env var)")


def get_tenant_id() -> str:
    """Get the "tenant id" from env (raise an exception if not set).

    Raises:
        BadConfigurationError: if the "tenant id" is not set.
    """
    if os.environ.get("DLOCK_TENANT_ID"):
        return os.environ["DLOCK_TENANT_ID"].lower().strip()
    raise BadConfigurationError(
        "You must provide a tenant_id (or set DLOCK_TENANT_ID env var)"
    )
