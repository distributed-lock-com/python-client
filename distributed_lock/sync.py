from __future__ import annotations

import datetime
import logging
import os
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from typing import Any

import httpx

from distributed_lock.const import DEFAULT_CLUSTER, DEFAULT_LIFETIME, DEFAULT_WAIT
from distributed_lock.exception import (
    BadConfigurationError,
    DistributedLockError,
    DistributedLockException,
    NotAcquiredError,
    NotAcquiredException,
    NotReleasedError,
    NotReleasedException,
)

logger = logging.getLogger("distributed-lock.sync")


def get_cluster() -> str:
    if os.environ.get("DLOCK_CLUSTER"):
        return os.environ["DLOCK_CLUSTER"].lower().strip()
    return DEFAULT_CLUSTER


def get_token() -> str:
    if os.environ.get("DLOCK_TOKEN"):
        return os.environ["DLOCK_TOKEN"].lower().strip()
    raise BadConfigurationError("You must provide a token (or set DLOCK_TOKEN env var)")


def get_tenant_id() -> str:
    if os.environ.get("DLOCK_TENANT_ID"):
        return os.environ["DLOCK_TENANT_ID"].lower().strip()
    raise BadConfigurationError(
        "You must provide a tenant_id (or set DLOCK_TENANT_ID env var)"
    )


def make_httpx_client() -> httpx.Client:
    timeout = httpx.Timeout(connect=10.0, read=65.0, write=10.0, pool=10.0)
    return httpx.Client(timeout=timeout)


@dataclass
class AcquiredRessource:
    resource: str
    lock_id: str

    @classmethod
    def from_dict(cls, d: dict) -> AcquiredRessource:
        for f in ("lock_id", "resource"):
            if f not in d:
                raise DistributedLockError(f"bad reply from service, missing {f}")
        return cls(resource=d["resource"], lock_id=d["lock_id"])

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DistributedLockClient:
    cluster: str = field(default_factory=get_cluster)
    token: str = field(default_factory=get_token)
    tenant_id: str = field(default_factory=get_tenant_id)
    client: httpx.Client = field(default_factory=make_httpx_client)
    user_agent: str | None = None
    service_wait: int = DEFAULT_WAIT

    def get_resource_url(self, resource: str) -> str:
        return f"https://{self.cluster}.distributed-lock.com/exclusive_locks/{self.tenant_id}/{resource}"

    def get_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def __del__(self):
        self.client.close()

    def _acquire(
        self,
        resource: str,
        lifetime: int = DEFAULT_LIFETIME,
        user_data: str | None = None,
    ) -> AcquiredRessource:
        body: dict[str, Any] = {"wait": self.service_wait, "lifetime": lifetime}
        if self.user_agent:
            body["user_agent"] = self.user_agent
        if user_data:
            body["user_data"] = user_data
        url = self.get_resource_url(resource)
        logger.debug(f"Try to lock {resource} with url: {url}...")
        try:
            r = self.client.post(url, json=body, headers=self.get_headers())
        except httpx.ConnectTimeout as e:
            logger.warning(f"connect timeout error during POST on {url}")
            raise NotAcquiredError("timeout during connect") from e
        except httpx.ReadTimeout as e:
            logger.warning(f"read timeout error during POST on {url}")
            raise NotAcquiredError("timeout during read") from e
        except httpx.WriteTimeout as e:
            logger.warning(f"write timeout error during POST on {url}")
            raise NotAcquiredError("timeout during write") from e
        except httpx.PoolTimeout as e:
            logger.warning("timeout in connection pool")
            raise NotAcquiredError("timeout in connection pool") from e
        except httpx.HTTPError as e:
            logger.warning("generic http error")
            raise NotAcquiredError("generic http error") from e
        if r.status_code == 409:
            logger.info(f"Lock on {resource} NOT acquired")
            raise NotAcquiredException()
        # FIXME other codes
        d = r.json()
        logger.info(f"Lock on {resource} acquired")
        return AcquiredRessource.from_dict(d)

    def acquire_exclusive_lock(
        self,
        resource: str,
        lifetime: int = DEFAULT_LIFETIME,
        wait: int = DEFAULT_WAIT,
        user_data: str | None = None,
        automatic_retry: bool = True,
        sleep_after_unsuccessful: float = 1.0,
    ) -> AcquiredRessource:
        before = datetime.datetime.utcnow()
        while True:
            catched_exception: Exception | None = None
            try:
                return self._acquire(
                    resource=resource, lifetime=lifetime, user_data=user_data
                )
            except DistributedLockError as e:
                if not automatic_retry:
                    raise
                catched_exception = e
            except DistributedLockException as e:
                catched_exception = e
            elapsed = (datetime.datetime.utcnow() - before).total_seconds()
            if elapsed > wait - sleep_after_unsuccessful:
                raise catched_exception
            logger.debug(f"wait {sleep_after_unsuccessful}s...")
            time.sleep(sleep_after_unsuccessful)
            if elapsed + sleep_after_unsuccessful + self.service_wait > wait:
                self.service_wait = max(
                    int(wait - elapsed - sleep_after_unsuccessful), 1
                )

    def _release(self, resource: str, lock_id: str):
        url = self.get_resource_url(resource) + "/" + lock_id
        logger.debug(f"Try to unlock {resource} with url: {url}...")
        try:
            r = self.client.delete(url, headers=self.get_headers())
        except httpx.ConnectTimeout as e:
            logger.warning(f"connect timeout error during DELETE on {url}")
            raise NotReleasedError("timeout during connect") from e
        except httpx.ReadTimeout as e:
            logger.warning(f"read timeout error during DELTE on {url}")
            raise NotReleasedError("timeout during read") from e
        except httpx.WriteTimeout as e:
            logger.warning(f"write timeout error during DELETE on {url}")
            raise NotReleasedError("timeout during write") from e
        except httpx.PoolTimeout as e:
            logger.warning("timeout in connection pool")
            raise NotReleasedError("timeout in connection pool") from e
        except httpx.HTTPError as e:
            logger.warning("generic http error")
            raise NotReleasedError("generic http error") from e
        if r.status_code == 409:
            logger.warning(
                f"Lock on {resource} NOT released (because it's acquired by another lock_id!)"
            )
            raise NotReleasedException()
        if r.status_code == 204:
            return
        logger.warning(
            f"Lock on {resource} NOT released (because of an unexpected status code: {r.status_code})"
        )
        raise NotReleasedError(f"unexpected status code: {r.status_code}")

    def release_exclusive_lock(
        self,
        resource: str,
        lock_id: str,
        wait: int = 30,
        automatic_retry: bool = True,
        sleep_after_unsuccessful: float = 1.0,
    ):
        before = datetime.datetime.utcnow()
        while True:
            catched_exception = None
            try:
                return self._release(resource=resource, lock_id=lock_id)
            except DistributedLockError as e:
                if not automatic_retry:
                    raise
                catched_exception = e
            elapsed = (datetime.datetime.utcnow() - before).total_seconds()
            if elapsed > wait - sleep_after_unsuccessful:
                raise catched_exception
            logger.debug(f"wait {sleep_after_unsuccessful}s...")
            time.sleep(sleep_after_unsuccessful)

    @contextmanager
    def exclusive_lock(
        self,
        resource: str,
        lifetime: int = DEFAULT_LIFETIME,
        wait: int = DEFAULT_WAIT,
        user_data: str | None = None,
        automatic_retry: bool = True,
        sleep_after_unsuccessful: float = 1.0,
    ):
        ar: AcquiredRessource | None = None
        try:
            ar = self.acquire_exclusive_lock(
                resource=resource,
                lifetime=lifetime,
                wait=wait,
                user_data=user_data,
                automatic_retry=automatic_retry,
                sleep_after_unsuccessful=sleep_after_unsuccessful,
            )
            yield
        finally:
            if ar is not None:
                self.release_exclusive_lock(
                    resource=resource,
                    lock_id=ar.lock_id,
                    wait=wait,
                    automatic_retry=automatic_retry,
                    sleep_after_unsuccessful=sleep_after_unsuccessful,
                )
