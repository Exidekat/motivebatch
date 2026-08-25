"""NMotive backend -- Motive's own exporter, driven through pythonnet.

NMotive.dll is a mixed-mode C++/CLI assembly: 25 MB of native x86-64 code with
an IJW native entry point.  Only the Windows CLR can load such an assembly, so
this backend is Windows-only by construction -- Mono and .NET on Linux/macOS
cannot load it at all, regardless of packaging.

Output from this backend is Motive's own, and is therefore the fidelity
reference the native backend approximates.
"""

import os
import sys

from .. import units as _units
from ..errors import BackendUnavailable, ExportNotSupported
from .base import AVI, BVH, C3D, CSV, FBX_ASCII, FBX_BINARY, TRC, Backend

#: CSVExporter toggles, mapped to our option names.  Motive's own export
#: dialog has these on, and a full export of a long take runs to gigabytes --
#: large output is expected here, not a symptom.
_CSV_TOGGLES = (
    ("WriteHeader", "header"),
    ("WriteMarkers", "markers"),
    ("WriteRigidBodies", "rigid_bodies"),
    ("WriteRigidBodyMarkers", "rigid_body_markers"),
    ("WriteBones", "bones"),
    ("WriteBoneMarkers", "bone_markers"),
    ("WriteQualityStats", "quality_stats"),
)

#: Export format -> NMotive exporter class name.
_EXPORTERS = {
    CSV: "CSVExporter",
    AVI: "VideoExporter",
    BVH: "BVHExporter",
    C3D: "C3DExporter",
    TRC: "TRCExporter",
    FBX_ASCII: "FBXExporter",
    FBX_BINARY: "FBXExporter",
}


class NMotiveBackend(Backend):
    name = "nmotive"
    formats = (CSV, AVI, BVH, C3D, TRC, FBX_ASCII, FBX_BINARY)

    def __init__(self, dll_path=None):
        self.dll_path = dll_path
        self.motive_root = None
        self._nm = None

    def describe(self):
        where = self.dll_path or "not located"
        if self.motive_root:
            where += "; Motive root " + self.motive_root
        return "nmotive (Motive's own exporter via pythonnet; Windows only) [{}]".format(where)

    # -- loading --------------------------------------------------------------

    def _load(self):
        """Import NMotive, raising BackendUnavailable with a precise reason."""
        if self._nm is not None:
            return self._nm

        if not sys.platform.startswith("win"):
            raise BackendUnavailable(
                self.name,
                "NMotive.dll is a mixed-mode C++/CLI assembly and can only be "
                "loaded by the Windows CLR (this is {})".format(sys.platform))

        try:
            import clr  # noqa: F401  (pythonnet)
        except ImportError:
            raise BackendUnavailable(
                self.name,
                "pythonnet is not installed (pip install pythonnet)")

        if not self.dll_path:
            raise BackendUnavailable(self.name, "NMotive.dll was not located")
        if not os.path.isfile(self.dll_path):
            raise BackendUnavailable(
                self.name, "no such file: {}".format(self.dll_path))

        _verify_assembly(self.dll_path, self.name)
        self.motive_root = prepare_native_environment(self.dll_path, self.name)

        import clr
        try:
            clr.AddReference(self.dll_path)
        except Exception:
            # Older pythonnet wants the directory on sys.path and a bare name.
            folder = os.path.dirname(os.path.abspath(self.dll_path))
            if folder not in sys.path:
                sys.path.append(folder)
            try:
                clr.AddReference(os.path.splitext(os.path.basename(self.dll_path))[0])
            except Exception as exc:
                raise BackendUnavailable(
                    self.name,
                    "could not load {}: {}. NMotive depends on sibling DLLs from "
                    "the Motive install (Qt and others); loading a copied-out "
                    "NMotive.dll on its own usually fails.".format(self.dll_path, exc))

        try:
            import NMotive
        except ImportError as exc:
            raise BackendUnavailable(
                self.name, "assembly loaded but the NMotive namespace is missing: {}".format(exc))

        self._nm = NMotive
        return NMotive

    # -- enum translation -----------------------------------------------------

    _LENGTH_ENUM = {
        _units.Meters: "Units_Meters",
        _units.Centimeters: "Units_Centimeters",
        _units.Millimeters: "Units_Millimeters",
    }

    def _length_units(self, nm, units):
        return getattr(nm.LengthUnits, self._LENGTH_ENUM[units])

    def _rotation(self, nm, rotation):
        if rotation == _units.Quaternions:
            return nm.Rotation.QuaternionFormat
        return getattr(nm.Rotation, rotation)

    # -- export ---------------------------------------------------------------

    def export(self, source, dest, fmt=CSV, markers=True, header=True,
               rotation=_units.Quaternions, units=_units.Meters,
               rigid_bodies=True, rigid_body_markers=None, bones=True,
               bone_markers=None, quality_stats=True, nmotive_set=None,
               progress=None, **_ignored):
        self.check(fmt)
        nm = self._load()
        take = nm.Take(os.path.abspath(source))

        exporter = getattr(nm, _EXPORTERS[fmt])()
        if fmt == CSV:
            exporter.RotationType = self._rotation(nm, rotation)
            exporter.Units = self._length_units(nm, units)
            # A None override leaves NMotive's own default in place; the
            # marker-dependent sets follow `markers` unless set explicitly.
            values = dict(header=header, markers=markers,
                          rigid_bodies=rigid_bodies,
                          rigid_body_markers=markers if rigid_body_markers is None
                          else rigid_body_markers,
                          bones=bones,
                          bone_markers=markers if bone_markers is None else bone_markers,
                          quality_stats=quality_stats)
            for prop, key in _CSV_TOGGLES:
                value = values.get(key)
                # Property names vary across NMotive releases; set what exists.
                if value is not None and hasattr(exporter, prop):
                    setattr(exporter, prop, bool(value))
            for prop, value in (nmotive_set or {}).items():
                if not hasattr(exporter, prop):
                    raise ExportNotSupported(
                        "this NMotive build has no CSVExporter property "
                        "{!r}; use --dump-exporter to list them".format(prop))
                setattr(exporter, prop, value)
        elif fmt in (FBX_ASCII, FBX_BINARY):
            # NMotive exposes both through one exporter with a format flag.
            if hasattr(exporter, "Binary"):
                exporter.Binary = (fmt == FBX_BINARY)

        target = os.path.abspath(dest)
        if progress is not None and getattr(progress, "enabled", False):
            from ..progress import pulse_while
            # Export must run here, on the thread that built take/exporter.
            # Poll the growing file so a multi-hour export visibly advances.
            with pulse_while(progress, watch=target):
                exporter.Export(take, target, True)
        else:
            exporter.Export(take, target, True)
        return dest

    def exporter_properties(self, fmt=CSV):
        """List an exporter's properties and current values.

        The available toggles differ between NMotive releases, and they cannot
        be enumerated anywhere but on a machine that can load the assembly.
        """
        nm = self._load()
        exporter = getattr(nm, _EXPORTERS[fmt])()
        out = []
        try:
            for prop in exporter.GetType().GetProperties():
                try:
                    value = getattr(exporter, prop.Name)
                except Exception:
                    value = "<unreadable>"
                out.append((prop.Name, value))
        except Exception:
            for name in sorted(dir(exporter)):
                if name.startswith("_"):
                    continue
                try:
                    value = getattr(exporter, name)
                except Exception:
                    continue
                if not callable(value):
                    out.append((name, value))
        return sorted(out)

    def take_info(self, source):
        nm = self._load()
        take = nm.Take(os.path.abspath(source))
        return {"frame_rate": float(take.FrameRate), "frame_count": None}


#: Handles returned by os.add_dll_directory must be kept alive, or the
#: directory is removed again when they are garbage collected.
_DLL_DIR_HANDLES = []

#: How far up from NMotive.dll to look for the Motive install root.
_ROOT_SEARCH_DEPTH = 5


def find_motive_root(dll_path):
    """Walk up from NMotive.dll to the Motive install directory.

    NMotive.dll lives in ``<root>\\assemblies\\x64``, while the Qt runtime and
    its ``platforms`` plugin directory live in ``<root>``.
    """
    folder = os.path.dirname(os.path.abspath(dll_path))
    for _ in range(_ROOT_SEARCH_DEPTH):
        if (os.path.isdir(os.path.join(folder, "platforms"))
                or os.path.isfile(os.path.join(folder, "Motive.exe"))):
            return folder
        parent = os.path.dirname(folder)
        if parent == folder:
            break
        folder = parent
    return None


def prepare_native_environment(dll_path, backend_name):
    """Point Qt at its plugins before NMotive.dll is loaded.

    NMotive links Qt, and Qt resolves its platform plugin relative to the host
    executable -- which here is python.exe, not Motive.exe.  Without this, Qt
    reports 'Could not find the Qt platform plugin "windows" in ""' and calls
    qFatal, aborting the process with 0xC0000409 before any Python exception
    handler can run.  So this must happen up front, not in a try/except.
    """
    root = find_motive_root(dll_path)
    if root is None:
        raise BackendUnavailable(
            backend_name,
            "found {} but not the Motive install directory above it. NMotive "
            "needs the Qt runtime and its platforms/ plugin folder from that "
            "directory; point --dll at the DLL inside a real Motive "
            "installation rather than a copied-out one.".format(dll_path))

    plugins = os.path.join(root, "platforms")
    if not os.path.isdir(plugins):
        raise BackendUnavailable(
            backend_name,
            "Motive root {} has no platforms/ folder, so Qt cannot start. "
            "This usually means NMotive.dll was copied out of a real "
            "installation.".format(root))

    # Qt reads these at initialisation; setting them later has no effect.
    os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = plugins
    os.environ.setdefault("QT_PLUGIN_PATH", root)

    # Let the loader find Qt5Core.dll and the other native siblings.
    for folder in (root, os.path.dirname(os.path.abspath(dll_path))):
        if not os.path.isdir(folder):
            continue
        adder = getattr(os, "add_dll_directory", None)
        if adder is not None:
            try:
                _DLL_DIR_HANDLES.append(adder(folder))
            except OSError:
                pass
        os.environ["PATH"] = folder + os.pathsep + os.environ.get("PATH", "")

    return root


def _verify_assembly(path, backend_name):
    """Reject a .tak-adjacent NMotive.dll that is obviously unloadable.

    A truncated or non-PE file produces a baffling CLR error deep inside
    pythonnet; checking the PE section table first turns that into a clear
    message.  This is exactly the failure mode of a partially-copied DLL.
    """
    import struct
    try:
        with open(path, "rb") as fh:
            head = fh.read(0x400)
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
    except OSError as exc:
        raise BackendUnavailable(backend_name, "cannot read {}: {}".format(path, exc))

    if head[:2] != b"MZ":
        raise BackendUnavailable(backend_name, "{} is not a Windows DLL".format(path))
    try:
        pe = struct.unpack_from("<I", head, 0x3C)[0]
        if head[pe:pe + 4] != b"PE\x00\x00":
            raise ValueError("no PE header")
        nsec = struct.unpack_from("<H", head, pe + 6)[0]
        opt_size = struct.unpack_from("<H", head, pe + 20)[0]
        sec_off = pe + 24 + opt_size
        needed = 0
        for i in range(nsec):
            base = sec_off + i * 40
            if base + 40 > len(head):
                return  # section table spills past our probe; let the CLR decide
            raw_size, raw_ptr = struct.unpack_from("<II", head, base + 16)
            needed = max(needed, raw_ptr + raw_size)
    except Exception:
        return  # Unparseable here is not proof of breakage; defer to the CLR.

    if needed and size < needed:
        raise BackendUnavailable(
            backend_name,
            "{} is truncated: the PE section table needs {} bytes but the file "
            "is {} ({} missing). Re-copy it from the Motive install.".format(
                path, needed, size, needed - size))
