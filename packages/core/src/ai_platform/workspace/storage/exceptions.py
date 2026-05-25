class ObjectNotFound(Exception):
    """Raised when a canonical object or file is not found in storage."""

    def __init__(self, message: str = "Object not found"):
        super().__init__(message)


class OptimisticConcurrencyError(Exception):
    """Raised when a versioned write loses to a concurrent writer.

    The caller passed `expected_version=N` to a repository's `put`,
    but the row currently in storage has a different version — meaning
    someone else updated it in the gap between the read and the write.
    """

    def __init__(self, message: str = "Optimistic concurrency check failed"):
        super().__init__(message)
