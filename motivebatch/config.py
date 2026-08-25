"""Locating NMotive.dll, and remembering where it was found.

Discovery order, first hit wins:

1. an explicit path (CLI argument or API call)
2. the ``NMOTIVE_DLL`` environment variable
3. the saved config file
4. the standard Motive install locations
5. alongside this repository (``temp/``, repo root)

Whatever finally works is written back to the config file so the user is asked
at most once.
"""

import json
import os
import sys

ENV_VAR = "NMOTIVE_DLL"
DLL_NAME = "NMotive.dll"

_INSTALL_GLOBS = (
    r"C:\Program Files\OptiTrack\Motive\assemblies\x64",
    r"C:\Program Files\OptiTrack\Motive\assemblies",
    r"C:\Program Files\OptiTrack\Motive",
    r"C:\Program Files (x86)\OptiTrack\Motive\assemblies\x64",
    r"C:\Program Files (x86)\OptiTrack\Motive",
)


def config_path():
    """Where the remembered DLL path lives."""
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.join(os.path.expanduser("~"), "Library", "Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "motivebatch", "config.json")


def load_config():
    try:
        with open(config_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_config(cfg):
    path = config_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2)
        return True
    except OSError:
        return False  # A read-only home is not worth failing an export over.


def remember_dll(path):
    cfg = load_config()
    cfg["nmotive_dll"] = os.path.abspath(path)
    return save_config(cfg)


def _repo_candidates():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return (os.path.join(here, "temp"), here)


def _normalise(path):
    """Accept either the DLL itself or a directory containing it."""
    if not path:
        return None
    path = os.path.expanduser(path)
    if os.path.isdir(path):
        path = os.path.join(path, DLL_NAME)
    return path if os.path.isfile(path) else None


def find_dll(explicit=None, use_config=True, search_install=True):
    """Return a path to NMotive.dll, or ``None``."""
    found = _normalise(explicit)
    if found:
        return found

    found = _normalise(os.environ.get(ENV_VAR))
    if found:
        return found

    if use_config:
        found = _normalise(load_config().get("nmotive_dll"))
        if found:
            return found

    if search_install:
        for folder in _INSTALL_GLOBS:
            found = _normalise(folder)
            if found:
                return found
        # A DLL dropped next to the checkout is the same kind of filesystem
        # search, so it is gated by the same flag.
        for folder in _repo_candidates():
            found = _normalise(folder)
            if found:
                return found

    return None


def prompt_for_dll(stream_in=None, stream_out=None):
    """Ask the user where NMotive.dll is.  Returns a path or ``None``.

    Returns ``None`` immediately when not attached to a terminal, so batch runs
    never hang waiting on input that will not come.
    """
    stream_in = stream_in or sys.stdin
    stream_out = stream_out or sys.stderr
    if not (hasattr(stream_in, "isatty") and stream_in.isatty()):
        return None

    stream_out.write(
        "\nCould not find NMotive.dll.\n"
        "It normally lives in C:\\Program Files\\OptiTrack\\Motive\\assemblies\\x64\\.\n"
        "Enter its full path (or press Enter to skip): ")
    stream_out.flush()
    try:
        answer = stream_in.readline().strip().strip('"')
    except (EOFError, KeyboardInterrupt):
        return None
    if not answer:
        return None

    path = _normalise(answer)
    if not path:
        stream_out.write("Not found: {}\n".format(answer))
        return None
    remember_dll(path)
    stream_out.write("Saved to {}\n".format(config_path()))
    return path
