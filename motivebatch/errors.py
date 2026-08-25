"""Exception hierarchy shared by every motivebatch backend."""


class MotiveBatchError(Exception):
    """Base class for all motivebatch errors."""


class TakFormatError(MotiveBatchError):
    """A .tak file could not be parsed."""


class BackendUnavailable(MotiveBatchError):
    """A backend cannot run in this environment.

    Carries a human-readable reason so the CLI can explain *why* a backend was
    skipped rather than just reporting that nothing worked.
    """

    def __init__(self, backend, reason):
        self.backend = backend
        self.reason = reason
        super().__init__("{} backend unavailable: {}".format(backend, reason))


class ExportNotSupported(MotiveBatchError):
    """The selected backend cannot produce the requested format."""
