"""Backend registry and selection.

NMotive is preferred wherever it can actually load, because its output is
Motive's own; the pure-Python backend is the portable fallback and the only
option off Windows.
"""

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
