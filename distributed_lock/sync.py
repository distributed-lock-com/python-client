from __future__ import annotations

import datetime
import functools
import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

import httpx

from distributed_lock.common import (
    AcquiredRessource,
    get_cluster,
    get_tenant_id,
    get_token,
)
from distributed_lock.const import DEFAULT_LIFETIME, DEFAULT_SERVER_SIDE_WAIT
from distributed_lock.exception import (
    DistributedLockError,
    DistributedLockException,
    NotAcquiredError,
    NotAcquiredException,
    NotReleasedError,
)

logger = logging.getLogger("distributed-lock.sync")


def make_httpx_client() -> httpx.Client:
    timeout = httpx.Timeout(connect=10.0, read=65.0, write=10.0, pool=10.0)
    return httpx.Client(timeout=timeout)


def with_retry(server_side_wait: bool = False):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            wait = kwargs.get("wait", DEFAULT_SERVER_SIDE_WAIT)
            automatic_retry = kwargs.get("automatic_retry", True)
            sleep_after_failure = kwargs.get("sleep_after_failure", 1.0)
            _forced_server_side_wait: float | None = None
            before = datetime.datetime.utcnow()
            while True:
                catched_exception: Exception | None = None
                try:
                    if _forced_server_side_wait is not None:
                        kwargs["_forced_server_side_wait"] = _forced_server_side_wait
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
                if server_side_wait:
                    if elapsed + sleep_after_failure + self.server_side_wait > wait:
                        _forced_server_side_wait = max(
                            int(wait - elapsed - sleep_after_failure), 1
                        )

        return wrapper

    return decorator


@dataclass
class DistributedLockClient:
    """Client object for https://distributed-lock.com service."""

    cluster: str = field(default_factory=get_cluster)
    """The cluster name to request.

    If not set, we will use the `DLOCK_CLUSTER` env var value (if set),
    else default value (`DEFAULT_CLUSTER`).
    """

    token: str = field(default_factory=get_token)
    """Your service token.

    If not set, we will use the `DLOCK_TOKEN` env var value (if set).
    Else, a `BadConfigurationError` will be raised.
    """

    tenant_id: str = field(default_factory=get_tenant_id)
    """Your tenant id.

    If not set, we will use the `DLOCK_TENANT_ID` env var value (if set).
    Else, a `BadConfigurationError` will be raised.
    """

    user_agent: str | None = None
    """Your 'user-agent'.

    Warning: this is not supported in all plans!
    """

    server_side_wait: int = DEFAULT_SERVER_SIDE_WAIT
    """Your "server side maximum wait" in seconds.

    The default value `DEFAULT_SERVER_SIDE_WAIT` is supported by all plans.
    If you pay for a better service, put your maximum supported value here.
    """

    _client: httpx.Client = field(default_factory=make_httpx_client)

    def get_resource_url(self, resource: str) -> str:
        """Return the full url of the given resource."""
        return f"https://{self.cluster}.distributed-lock.com/exclusive_locks/{self.tenant_id}/{resource}"

    def _get_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def __del__(self):
        self._client.close()

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
            r = self._client.request(method, url, json=body, headers=headers)
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
                raise error_class(
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
        user_data: dict | list | str | float | int | bool | None = None,
        server_side_wait: float | None = None,
    ) -> AcquiredRessource:
        body: dict[str, Any] = {
            "wait": min(
                server_side_wait or self.server_side_wait, self.server_side_wait
            ),
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
            headers=self._get_headers(),
            body=body,
            error_class=NotAcquiredError,
            exception_class=NotAcquiredException,
        )
        d = r.json()
        logger.info(f"Lock on {resource} acquired")
        return AcquiredRessource.from_dict(d)

    @with_retry(server_side_wait=True)
    def acquire_exclusive_lock(
        self,
        resource: str,
        *,
        lifetime: int = DEFAULT_LIFETIME,
        wait: int = DEFAULT_SERVER_SIDE_WAIT,
        user_data: dict | list | str | float | int | bool | None = None,
        automatic_retry: bool = True,
        sleep_after_failure: float = 1.0,
        _forced_server_side_wait: float | None = None,
    ) -> AcquiredRessource:
        """Acquire an exclusive lock on the given resource.

        Notes:
            - the wait parameter is implemented as a mix of:
                - server side wait (without polling) thanks to the server_side_wait property
                - client side wait (with multiple calls if automatic_retry=True default)
            - the most performant way to configure this is:
                - to set server_side_wait (when creating the DistributedLockClient object)
                  to the highest value allowed by your plan
                - use the wait parameter here at the value of your choice

        Args:
            resource: the resource name to acquire.
            lifetime: the lock max lifetime (in seconds).
            wait: the maximum wait (in seconds) for acquiring the lock.
            user_data: user_data to store with the lock (warning: it's not allowed with
                all plans).
            automatic_retry: if the operation fails (because of some errors or because the
                lock is already held by someone else), if set to True, we are going to
                try multiple times until the maximum wait delay.
            sleep_after_failure: when doing multiple client side retry, let's sleep during
                this number of seconds before retrying.
            _forced_server_side_wait: don't use it (it's internal use only).

        Returns:
            An object `AcquiredRessource`. Note: you will need the lock_id field
                of this object to call `release_exclusive_lock()`.

        Raises:
            NotAcquiredException: Can't acquire the lock (even after the wait time
                and after automatic retries) because it's already held by
                someone else after the wait time.
            NotAcquiredError: Can't acquire the lock (even after the wait time
                and after automatic retries) because some other errors raised.

        """
        return self._acquire(
            resource=resource,
            lifetime=lifetime,
            user_data=user_data,
            server_side_wait=_forced_server_side_wait,
        )

    def _release(self, resource: str, lock_id: str):
        url = self.get_resource_url(resource) + "/" + lock_id
        logger.debug(f"Try to unlock {resource} with url: {url}...")
        self._request(
            "DELETE",
            url,
            headers=self._get_headers(),
            body=None,
            error_class=NotReleasedError,
            exception_class=NotReleasedError,
        )

    @with_retry(server_side_wait=False)
    def release_exclusive_lock(
        self,
        resource: str,
        lock_id: str,
        *,
        wait: int = 10,
        automatic_retry: bool = True,
        sleep_after_failure: float = 1.0,
    ):
        """Release an exclusive lock on the given resource.

        Notes:
            - the wait parameter is only a "client side wait"
                (with multiple calls if automatic_retry=True default).

        Args:
            resource: the resource name to acquire.
            lock_id: the lock unique identifier (field of `AcquiredRessource` object)
            wait: the maximum wait (in seconds) for acquiring the lock.
            automatic_retry: if the operation fails (because of some errors or because the
                lock is already held by someone else), if set to True, we are going to
                try multiple times until the maximum wait delay.
            sleep_after_failure: when doing multiple client side retry, let's sleep during
                this number of seconds before retrying.
            _forced_server_side_wait: don't use it (it's internal use only).

        Raises:
            NotReleasedError: Can't release the lock (even after the wait time
                and after automatic retries) because some errors raised.

        """
        return self._release(resource=resource, lock_id=lock_id)

    @contextmanager
    def exclusive_lock(
        self,
        resource: str,
        lifetime: int = DEFAULT_LIFETIME,
        wait: int = DEFAULT_SERVER_SIDE_WAIT,
        user_data: str | None = None,
        automatic_retry: bool = True,
        sleep_after_failure: float = 1.0,
    ):
        """Acquire an exclusive lock and release it as a context manager.

        Notes:
            - the wait parameter is implemented as a mix of:
                - server side wait (without polling) thanks to the server_side_wait property
                - client side wait (with multiple calls if automatic_retry=True default)
            - the most performant way to configure this is:
                - to set server_side_wait (when creating the DistributedLockClient object)
                  to the highest value allowed by your plan
                - use the wait parameter here at the value of your choice

        Args:
            resource: the resource name to acquire.
            lifetime: the lock max lifetime (in seconds).
            wait: the maximum wait (in seconds) for acquiring the lock.
            user_data: user_data to store with the lock (warning: it's not allowed with
                all plans).
            automatic_retry: if the operation fails (because of some errors or because the
                lock is already held by someone else), if set to True, we are going to
                try multiple times until the maximum wait delay.
            sleep_after_failure: when doing multiple client side retry, let's sleep during
                this number of seconds before retrying.

        Raises:
            NotAcquiredException: Can't acquire the lock (even after the wait time
                and after automatic retries) because it's already held by
                someone else after the wait time.
            NotAcquiredError: Can't acquire the lock (even after the wait time
                and after automatic retries) because some other errors raised.

        """
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
