from __future__ import annotations


class DistributedLockException(Exception):
    """Base class for lock exceptions."""

    pass


class DistributedLockError(Exception):
    """Base class for lock errors."""

    pass


class BadConfigurationError(DistributedLockError):
    """Bad configuration."""

    pass


class NotAcquiredException(DistributedLockException):
    """Not acquired because the lock is still held by someone else."""

    pass


class NotReleasedError(DistributedLockError):
    """Not released lock because some errors popped during the lock release."""

    pass


class NotAcquiredError(DistributedLockError):
    """Not acquired because some errors popped during the lock acquisition."""

    pass
