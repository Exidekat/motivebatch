"""Backend registry and selection.

NMotive is preferred wherever it can actually load, because its output is
Motive's own; the pure-Python backend is the portable fallback and the only
option off Windows.
"""

import os
import sys

from .. import config as _config
from ..errors import BackendUnavailable, ExportNotSupported
from .base import ALL_FORMATS, CSV, Backend
from .native import NativeBackend
from .nmotive import NMotiveBackend

NATIVE = "native"
NMOTIVE = "nmotive"
AUTO = "auto"

CHOICES = (AUTO, NMOTIVE, NATIVE)


def build(preference=AUTO, dll_path=None, fmt=CSV, allow_prompt=True,
          use_config=True, log=None):
    """Pick a backend.

    Returns ``(backend, notes)`` where ``notes`` lists human-readable reasons a
    backend was skipped, so callers can explain the choice.
    """
    notes = []

    def _note(msg):
        notes.append(msg)
        if log:
            log(msg)

    want_nmotive = preference in (AUTO, NMOTIVE)
    native_can = fmt == CSV

    if want_nmotive:
        found = _config.find_dll(dll_path, use_config=use_config)
        if found is None and allow_prompt and (preference == NMOTIVE or not native_can):
            # Only interrupt the user when NMotive is genuinely required.
            found = _config.prompt_for_dll()
        candidate = NMotiveBackend(found)
        try:
            candidate.check(fmt)
            candidate._load()
        except (BackendUnavailable, ExportNotSupported) as exc:
            if preference == NMOTIVE:
                raise
            _note(str(exc))
        else:
            if found:
                _config.remember_dll(found)
            return candidate, notes

    if preference == NMOTIVE:
        raise BackendUnavailable(NMOTIVE, "no usable NMotive installation was found")

    native = NativeBackend()
    native.check(fmt)  # raises ExportNotSupported for AVI/BVH/... off Windows
    return native, notes


#: Substrings in a backend error that the portable reader may well survive.
_RECOVERABLE_HINTS = (
    "newer software version",   # take recorded by a newer Motive than is installed
    "cannot be read",
    "unsupported",
)


def explain_failure(exc):
    """Turn a backend exception into an actionable one-liner, when we can."""
    text = str(exc)
    if "newer software version" in text:
        return ("this take was recorded by a newer version of Motive than the "
                "one installed here, so NMotive refuses to open it")
    return text


def fallback_default():
    """Whether a failed NMotive export should retry with the portable reader.

    Off by default on Windows: a machine with Motive installed is expected to
    produce Motive's own output, so a silent downgrade to best-effort fidelity
    would be worse than a clear failure.  Elsewhere NMotive cannot run at all,
    so the question does not arise.
    """
    return not sys.platform.startswith("win")


def export_with_fallback(backend, source, dest, fmt=CSV, preference=AUTO,
                         options=None, log=None, allow_fallback=None):
    """Export, optionally retrying with the portable reader when NMotive fails.

    NMotive raises .NET exceptions that are not MotiveBatchError, and it fails
    at export time rather than load time -- a take from a newer Motive than the
    one installed is the common case.  The pure-Python reader is version
    agnostic, but substituting it changes the fidelity of the result, so on
    Windows that only happens when explicitly asked for.
    """
    options = options or {}
    if allow_fallback is None:
        allow_fallback = fallback_default()
    try:
        return backend.export(source, dest, fmt=fmt, **options)
    except ExportNotSupported:
        raise
    except Exception as exc:
        # A half-written export must never survive the failure that produced
        # it; a broken CSV on the Desktop reads as success.
        _discard(dest)
        can_retry = (allow_fallback and preference == AUTO
                     and fmt == CSV and backend.name == NMOTIVE)
        if not can_retry:
            if log and backend.name == NMOTIVE and fmt == CSV and not allow_fallback:
                log("Not falling back to the portable reader; pass "
                    "--allow-fallback to convert this take at best-effort fidelity.")
            raise
        bar = options.get("progress")
        if bar is not None:
            bar.clear()
        if log:
            log("{} could not export this take: {}".format(backend.name, explain_failure(exc)))
            log("Falling back to the portable reader.")
        return NativeBackend().export(source, dest, fmt=fmt, **options)


def _discard(path):
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass  # Losing the cleanup is not worth masking the original error.


def available(dll_path=None):
    """Describe every backend and whether it can run here."""
    out = []
    nm = NMotiveBackend(_config.find_dll(dll_path))
    try:
        nm._load()
        out.append((NMOTIVE, True, nm.describe()))
    except BackendUnavailable as exc:
        out.append((NMOTIVE, False, exc.reason))
    out.append((NATIVE, True, NativeBackend().describe()))
    return out


__all__ = ["build", "available", "Backend", "NativeBackend", "NMotiveBackend",
           "CHOICES", "AUTO", "NATIVE", "NMOTIVE", "ALL_FORMATS"]
