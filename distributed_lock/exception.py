from __future__ import annotations


class DistributedLockException(Exception):
    pass


class DistributedLockError(DistributedLockException):
    pass


class BadConfigurationError(DistributedLockError):
    pass


class NotAcquiredException(DistributedLockException):
    pass


class NotReleasedException(DistributedLockException):
    pass


class NotReleasedError(DistributedLockError):
    pass


class NotAcquiredError(DistributedLockError):
    pass
