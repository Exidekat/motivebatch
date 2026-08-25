"""Command-line interface.

Positional arguments are classified by extension, so all of these work and the
wrapper scripts can simply forward their arguments verbatim::

    motivebatch take.tak
    motivebatch NMotive.dll take.tak
    motivebatch take.tak NMotive.dll other.tak
"""

import argparse
import os
import sys

from . import __version__
from . import backends as _backends
from . import config as _config
from . import units as _units
from .progress import NullProgress, Progress
from .backends import base as _fmt
from .errors import MotiveBatchError

_ROTATIONS = {"quaternion": _units.Quaternions, "quaternions": _units.Quaternions}
for _o in _units.EULER_ORDERS:
    _ROTATIONS[_o.lower()] = _o

_UNITS = {
    "m": _units.Meters, "meters": _units.Meters, "metres": _units.Meters,
    "cm": _units.Centimeters, "centimeters": _units.Centimeters,
    "mm": _units.Millimeters, "millimeters": _units.Millimeters,
}


def desktop_dir():
    """Best guess at the user's Desktop, or ``None``.

    Handles the OneDrive-redirected Desktop that is now the Windows default.
    """
    home = os.path.expanduser("~")
    candidates = [os.path.join(home, "Desktop")]
    if sys.platform.startswith("win"):
        onedrive = os.environ.get("OneDrive") or os.environ.get("OneDriveConsumer")
        if onedrive:
            candidates.insert(0, os.path.join(onedrive, "Desktop"))
        profile = os.environ.get("USERPROFILE")
        if profile:
            candidates.append(os.path.join(profile, "OneDrive", "Desktop"))
            candidates.append(os.path.join(profile, "Desktop"))
    for c in candidates:
        if os.path.isdir(c):
            return c
    return None


def unique_path(path):
    """``foo.csv`` -> ``foo (1).csv`` if taken, so nothing is overwritten."""
    if not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(path)
    n = 1
    while True:
        candidate = "{} ({}){}".format(stem, n, ext)
        if not os.path.exists(candidate):
            return candidate
        n += 1


def build_parser():
    p = argparse.ArgumentParser(
        prog="motivebatch",
        description="Convert OptiTrack Motive .tak files to CSV (and more on Windows).",
        epilog="Arguments are matched by extension: .tak files are inputs, "
               "a .dll is treated as the path to NMotive.dll.")
    p.add_argument("paths", nargs="*", metavar="PATH",
                   help=".tak files to convert, and optionally NMotive.dll")
    p.add_argument("--dll", metavar="PATH", help="explicit path to NMotive.dll")
    p.add_argument("--backend", choices=_backends.CHOICES, default=_backends.AUTO,
                   help="which exporter to use (default: auto)")
    p.add_argument("--format", dest="fmt", default=_fmt.CSV,
                   choices=list(_fmt.ALL_FORMATS), help="export format (default: csv)")

    out = p.add_argument_group("output location")
    out.add_argument("-o", "--output", metavar="FILE",
                     help="exact output file (only valid with a single input)")
    out.add_argument("--output-dir", metavar="DIR", help="write outputs into DIR")
    out.add_argument("--beside-input", action="store_true",
                     help="write next to each .tak instead of the Desktop")
    out.add_argument("--overwrite", action="store_true",
                     help="replace an existing file instead of adding a ' (1)' suffix")

    exp = p.add_argument_group("export options")
    exp.add_argument("--markers", dest="markers", action="store_true", default=True,
                     help="include marker positions (default, as Motive does)")
    exp.add_argument("--no-markers", dest="markers", action="store_false",
                     help="rigid bodies only; much smaller files")
    exp.add_argument("--bones", dest="bones", action="store_true", default=True,
                     help="include skeleton bones (default; NMotive only)")
    exp.add_argument("--no-bones", dest="bones", action="store_false")
    exp.add_argument("--quality-stats", dest="quality_stats", action="store_true",
                     default=True, help="include quality statistics (default; NMotive only)")
    exp.add_argument("--no-quality-stats", dest="quality_stats", action="store_false")
    exp.add_argument("--nmotive-set", metavar="NAME=VALUE", action="append", default=[],
                     help="set any exporter property directly (repeatable)")
    exp.add_argument("--header", dest="header", action="store_true", default=True,
                     help="write the descriptive header block (default)")
    exp.add_argument("--no-header", dest="header", action="store_false")
    exp.add_argument("--rotation", default="quaternion",
                     choices=sorted(_ROTATIONS), help="rotation representation")
    exp.add_argument("--units", default="meters", choices=sorted(_UNITS),
                     help="length units (default: meters)")
    exp.add_argument("--frame-rate", type=float, default=None,
                     help="override the capture frame rate")

    misc = p.add_argument_group("other")
    misc.add_argument("--info", action="store_true", help="describe the take, do not export")
    misc.add_argument("--list-backends", action="store_true",
                      help="show which backends can run here, then exit")
    misc.add_argument("--dump-exporter", action="store_true",
                      help="list the NMotive exporter's properties and defaults, then exit")
    misc.add_argument("--find-dll", action="store_true",
                      help="print the located NMotive.dll path (empty if none), then exit")
    misc.add_argument("--allow-fallback", dest="allow_fallback",
                      action="store_true", default=None,
                      help="if NMotive cannot export a take, retry with the "
                           "portable reader (off by default on Windows)")
    misc.add_argument("--no-fallback", dest="allow_fallback",
                      action="store_false",
                      help="never substitute the portable reader for NMotive")
    misc.add_argument("--no-prompt", action="store_true",
                      help="never ask interactively for the NMotive.dll path")
    misc.add_argument("--no-progress", dest="progress", action="store_false",
                      default=True, help="do not draw a progress bar")
    misc.add_argument("-v", "--verbose", action="store_true",
                      help="explain why a backend was or was not chosen")
    misc.add_argument("-q", "--quiet", action="store_true")
    misc.add_argument("--version", action="version", version="motivebatch " + __version__)
    return p


def _classify(paths):
    """Split positionals into (.tak inputs, NMotive.dll path)."""
    inputs, dll = [], None
    for p in paths:
        if p.lower().endswith(".dll"):
            dll = p
        else:
            inputs.append(p)
    return inputs, dll


def _destination(src, args, ext, log):
    if args.output:
        return args.output
    if args.output_dir:
        folder = args.output_dir
    elif args.beside_input:
        folder = os.path.dirname(os.path.abspath(src))
    else:
        folder = desktop_dir()
        if folder is None:
            folder = os.path.dirname(os.path.abspath(src))
            log("Could not locate a Desktop folder; writing beside the input instead.")
    name = os.path.splitext(os.path.basename(src))[0] + ext
    dest = os.path.join(folder, name)
    return dest if args.overwrite else unique_path(dest)


def main(argv=None):
    args = build_parser().parse_args(argv)

    def log(msg):
        if not args.quiet:
            sys.stderr.write(msg + "\n")

    inputs, positional_dll = _classify(args.paths)
    dll = args.dll or positional_dll

    if args.dump_exporter:
        from .backends.nmotive import NMotiveBackend
        backend = NMotiveBackend(_config.find_dll(dll))
        try:
            props = backend.exporter_properties(args.fmt)
        except MotiveBatchError as exc:
            sys.stderr.write("Error: {}\n".format(exc))
            return 1
        for name, value in props:
            sys.stdout.write("{:28} {}\n".format(name, value))
        return 0

    if args.find_dll:
        found = _config.find_dll(dll)
        if found:
            sys.stdout.write(found + "\n")
        return 0 if found else 1

    if args.list_backends:
        for name, ok, detail in _backends.available(dll):
            sys.stdout.write("{:9} {}  {}\n".format(name, "OK     " if ok else "no", detail))
        sys.stdout.write("\nConfig file: {}\n".format(_config.config_path()))
        return 0

    if not inputs:
        build_parser().print_usage(sys.stderr)
        sys.stderr.write("\nNo .tak file given.\n")
        return 2
    if args.output and len(inputs) > 1:
        sys.stderr.write("--output takes a single input file; use --output-dir instead.\n")
        return 2

    rotation = _ROTATIONS[args.rotation]
    units = _UNITS[args.units]

    nmotive_set = {}
    for item in args.nmotive_set:
        if "=" not in item:
            sys.stderr.write("--nmotive-set expects NAME=VALUE, got {!r}\n".format(item))
            return 2
        name, _, raw = item.partition("=")
        low = raw.strip().lower()
        if low in ("true", "false"):
            value = (low == "true")
        else:
            try:
                value = int(raw)
            except ValueError:
                value = raw
        nmotive_set[name.strip()] = value

    try:
        backend, notes = _backends.build(
            args.backend, dll_path=dll, fmt=args.fmt,
            allow_prompt=not args.no_prompt, log=None)
    except MotiveBatchError as exc:
        sys.stderr.write("Error: {}\n".format(exc))
        return 1

    # Off Windows, "NMotive cannot load here" is a fact of the platform, not
    # something the user can act on -- so it stays quiet unless asked for.
    if args.verbose or sys.platform.startswith("win"):
        for n in notes:
            log("note: {}".format(n))
        if backend.name == _backends.NATIVE and args.fmt == _fmt.CSV:
            log("Using the portable reader: column values are exact, but the "
                "header block is a best-effort match for Motive's own exporter.")
    log("Using the {} backend.".format(backend.name))

    show_progress = args.progress and not args.quiet
    failures = 0
    for index, src in enumerate(inputs, start=1):
        if not os.path.isfile(src):
            sys.stderr.write("Error: no such file: {}\n".format(src))
            failures += 1
            continue
        if args.info:
            failures += _show_info(src, backend, log)
            continue
        dest = _destination(src, args, "." + _ext_for(args.fmt), log)
        label = os.path.basename(src)
        if len(inputs) > 1:
            label = "[{}/{}] {}".format(index, len(inputs), label)
        bar = Progress(label) if show_progress else NullProgress()
        try:
            folder = os.path.dirname(os.path.abspath(dest))
            if folder and not os.path.isdir(folder):
                os.makedirs(folder, exist_ok=True)
            _backends.export_with_fallback(
                backend, src, dest, fmt=args.fmt, preference=args.backend,
                options=dict(markers=args.markers, header=args.header,
                             rotation=rotation, units=units,
                             frame_rate=args.frame_rate, bones=args.bones,
                             quality_stats=args.quality_stats,
                             nmotive_set=nmotive_set, progress=bar),
                log=log, allow_fallback=args.allow_fallback)
        except MotiveBatchError as exc:
            bar.clear()
            sys.stderr.write("Error converting {}: {}\n".format(src, exc))
            failures += 1
        except (OSError, IOError) as exc:
            bar.clear()
            sys.stderr.write("Error writing {}: {}\n".format(dest, exc))
            failures += 1
        except Exception as exc:
            bar.clear()
            # Backends can raise foreign exception types (NMotive surfaces .NET
            # ones); report them cleanly and keep going through the batch.
            sys.stderr.write("Error converting {}: {}\n".format(
                src, _backends.explain_failure(exc)))
            failures += 1
        else:
            sys.stdout.write("{}\n".format(dest))
    return 1 if failures else 0


def _ext_for(fmt):
    return {_fmt.FBX_ASCII: "fbx", _fmt.FBX_BINARY: "fbx"}.get(fmt, fmt)


def _show_info(src, backend, log):
    from .tak import load
    try:
        doc = load(src)
    except MotiveBatchError as exc:
        sys.stderr.write("Error reading {}: {}\n".format(src, exc))
        return 1
    first, last = doc.frame_range
    sys.stdout.write(
        "{}\n"
        "  frames        {} ({}..{})\n"
        "  frame rate    {}\n"
        "  rigid bodies  {}\n"
        "  markers       {}\n"
        "  cameras       {}\n"
        "  streams       {}\n".format(
            os.path.abspath(src), doc.frame_count, first, last,
            doc.frame_rate if doc.frame_rate else "unknown",
            len(doc.rigid_bodies), len(doc.markers), len(doc.cameras),
            ", ".join(doc.ole.stream_names)))
    for rb in doc.rigid_bodies:
        sys.stdout.write("    rigid body  {:<28} id={}\n".format(rb.name or "?", rb.id or "?"))
    return 0
