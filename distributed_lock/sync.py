from __future__ import annotations

import datetime
import functools
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


def with_retry(service_wait: bool = False):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            wait = kwargs.get("wait", DEFAULT_WAIT)
            automatic_retry = kwargs.get("automatic_retry", True)
            sleep_after_failure = kwargs.get("sleep_after_failure", 1.0)
            _forced_service_wait: float | None = None
            before = datetime.datetime.utcnow()
            while True:
                catched_exception: Exception | None = None
                try:
                    if _forced_service_wait is not None:
                        kwargs["_forced_service_wait"] = _forced_service_wait
                    return func(self, *args, **kwargs)
                except DistributedLockError as e:
                    if not automatic_retry:
                        raise
                    catched_exception = e
                except DistributedLockException as e:
                    catched_exception = e
                elapsed = (datetime.datetime.utcnow() - before).total_seconds()
                if elapsed > wait - sleep_after_failure:
                    raise catched_exception
                logger.debug(f"wait {sleep_after_failure}s...")
                time.sleep(sleep_after_failure)
                if service_wait:
                    if elapsed + sleep_after_failure + self.service_wait > wait:
                        _forced_service_wait = max(
                            int(wait - elapsed - sleep_after_failure), 1
                        )

        return wrapper

    return decorator


@dataclass
class AcquiredRessource:
    resource: str
    lock_id: str
    tenant_id: str
    created: datetime.datetime = field(default_factory=datetime.datetime.utcnow)
    expires: datetime.datetime = field(default_factory=datetime.datetime.utcnow)
    user_agent: str = ""
    user_data: Any = ""

    @classmethod
    def from_dict(cls, d: dict) -> AcquiredRessource:
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
                d2[f] = datetime.datetime.fromisoformat(d2[f])
        return cls(**d2)

    def to_dict(self) -> dict:
        d = asdict(self)
        for f in ("created", "expires"):
            d[f] = d[f].isoformat()[0:19] + "Z"
        return d


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

    def _request(
        self,
        method: str,
        url: str,
        headers: dict,
        body: dict | None,
        error_class,
        exception_class,
    ):
        try:
            r = self.client.request(method, url, json=body, headers=headers)
        except httpx.ConnectTimeout as e:
            raise error_class("timeout during connect") from e
        except httpx.ReadTimeout as e:
            raise error_class("timeout during read") from e
        except httpx.WriteTimeout as e:
            raise error_class("timeout during write") from e
        except httpx.PoolTimeout as e:
            raise error_class("timeout in connection pool") from e
        except httpx.HTTPError as e:
            raise error_class("generic http error") from e
        if r.status_code == 409:
            raise exception_class("got a HTTP/409 Conflict")
        elif r.status_code == 403:
            try:
                raise error_class(
                    f"got a HTTP/403 Forbidden error with message: {r.json()['message']}"
                )
            except Exception:
                raise error_class("got an HTTP/403 Forbidden with no detail") from None
        elif r.status_code == 429:
            try:
                logger.warning(
                    f"got a HTTP/429 Rate limited error with message: {r.json()['message']}"
                )
            except Exception:
                raise error_class("got an HTTP/429 Forbidden with no detail") from None
        elif r.status_code < 200 or r.status_code >= 300:
            raise error_class(f"unexpected status code: {r.status_code}")
        return r

    def _acquire(
        self,
        resource: str,
        lifetime: int = DEFAULT_LIFETIME,
        user_data: str | None = None,
        forced_service_wait: float | None = None,
    ) -> AcquiredRessource:
        body: dict[str, Any] = {
            "wait": forced_service_wait
            if forced_service_wait is not None
            else self.service_wait,
            "lifetime": lifetime,
        }
        if self.user_agent:
            body["user_agent"] = self.user_agent
        if user_data:
            body["user_data"] = user_data
        url = self.get_resource_url(resource)
        logger.debug(f"Try to lock {resource} with url: {url}...")
        r = self._request(
            "POST",
            url,
            headers=self.get_headers(),
            body=body,
            error_class=NotAcquiredError,
            exception_class=NotAcquiredException,
        )
        d = r.json()
        logger.info(f"Lock on {resource} acquired")
        return AcquiredRessource.from_dict(d)

    @with_retry(service_wait=True)
    def acquire_exclusive_lock(
        self,
        resource: str,
        *,
        lifetime: int = DEFAULT_LIFETIME,
        wait: int = DEFAULT_WAIT,
        user_data: str | None = None,
        automatic_retry: bool = True,
        sleep_after_failure: float = 1.0,
        _forced_service_wait: float | None = None,
    ) -> AcquiredRessource:
        return self._acquire(
            resource=resource,
            lifetime=lifetime,
            user_data=user_data,
            forced_service_wait=_forced_service_wait,
        )

    def _release(self, resource: str, lock_id: str):
        url = self.get_resource_url(resource) + "/" + lock_id
        logger.debug(f"Try to unlock {resource} with url: {url}...")
        self._request(
            "DELETE",
            url,
            headers=self.get_headers(),
            body=None,
            error_class=NotReleasedError,
            exception_class=NotReleasedError,
        )

    @with_retry()
    def release_exclusive_lock(
        self,
        resource: str,
        lock_id: str,
        *,
        wait: int = 30,
        automatic_retry: bool = True,
        sleep_after_failure: float = 1.0,
    ):
        return self._release(resource=resource, lock_id=lock_id)

    @contextmanager
    def exclusive_lock(
        self,
        resource: str,
        lifetime: int = DEFAULT_LIFETIME,
        wait: int = DEFAULT_WAIT,
        user_data: str | None = None,
        automatic_retry: bool = True,
        sleep_after_failure: float = 1.0,
    ):
        ar: AcquiredRessource | None = None
        try:
            ar = self.acquire_exclusive_lock(
                resource=resource,
                lifetime=lifetime,
                wait=wait,
                user_data=user_data,
                automatic_retry=automatic_retry,
                sleep_after_failure=sleep_after_failure,
            )
            yield
        finally:
            if ar is not None:
                self.release_exclusive_lock(
                    resource=resource,
                    lock_id=ar.lock_id,
                    wait=wait,
                    automatic_retry=automatic_retry,
                    sleep_after_failure=sleep_after_failure,
                )
