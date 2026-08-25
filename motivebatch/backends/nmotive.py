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
from ..errors import BackendUnavailable
from .base import AVI, BVH, C3D, CSV, FBX_ASCII, FBX_BINARY, TRC, Backend

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
        self._nm = None

    def describe(self):
        where = self.dll_path or "not located"
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

    def export(self, source, dest, fmt=CSV, markers=False, header=True,
               rotation=_units.Quaternions, units=_units.Meters, **_ignored):
        self.check(fmt)
        nm = self._load()
        take = nm.Take(os.path.abspath(source))

        exporter = getattr(nm, _EXPORTERS[fmt])()
        if fmt == CSV:
            exporter.RotationType = self._rotation(nm, rotation)
            exporter.WriteMarkers = markers
            exporter.WriteHeader = header
            exporter.Units = self._length_units(nm, units)
        elif fmt in (FBX_ASCII, FBX_BINARY):
            # NMotive exposes both through one exporter with a format flag.
            if hasattr(exporter, "Binary"):
                exporter.Binary = (fmt == FBX_BINARY)

        exporter.Export(take, os.path.abspath(dest), True)
        return dest

    def take_info(self, source):
        nm = self._load()
        take = nm.Take(os.path.abspath(source))
        return {"frame_rate": float(take.FrameRate), "frame_count": None}


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
