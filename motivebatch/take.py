"""The Take object -- a small OOP wrapper over whichever backend is available.

Kept API-compatible with the original IronPython version, minus the import-time
DLL dependency: ``import motivebatch`` now works on any machine.
"""

import os

from . import backends as _backends
from . import units as _units
from .backends import base as _fmt
from .errors import MotiveBatchError

# Re-exported so ``from motivebatch import Take, Meters`` keeps working.
Meters = _units.Meters
Centimeters = _units.Centimeters
Millimeters = _units.Millimeters
Quaternions = _units.Quaternions
for _o in _units.EULER_ORDERS:
    globals()[_o] = _o
del _o


class Take(object):
    """A Motive take file.

    ``backend`` is ``"auto"`` (default), ``"nmotive"`` or ``"native"``.
    """

    def __init__(self, fname, backend=_backends.AUTO, dll_path=None):
        path = os.path.expanduser(fname)
        if not os.path.split(path)[0]:
            path = os.path.join(".", path)
        if not os.path.exists(path):
            raise IOError("FileNotFound: {}".format(os.path.abspath(path)))
        self.fname = os.path.abspath(path)
        self._preference = backend
        self._dll_path = dll_path
        self._backends = {}
        self._info = None

    # -- backend plumbing -----------------------------------------------------

    def backend_for(self, fmt):
        """The backend that will handle ``fmt``, chosen on first use."""
        if fmt not in self._backends:
            backend, notes = _backends.build(
                self._preference, dll_path=self._dll_path, fmt=fmt)
            self._backends[fmt] = backend
            self.selection_notes = notes
        return self._backends[fmt]

    @property
    def backend_name(self):
        return self.backend_for(_fmt.CSV).name

    # -- metadata -------------------------------------------------------------

    def _take_info(self):
        if self._info is None:
            self._info = self.backend_for(_fmt.CSV).take_info(self.fname)
        return self._info

    @property
    def frame_rate(self):
        return self._take_info().get("frame_rate")

    @property
    def frame_count(self):
        return self._take_info().get("frame_count")

    # -- export ---------------------------------------------------------------

    def _dest(self, fname, ext):
        if fname:
            return os.path.expanduser(fname)
        return os.path.splitext(self.fname)[0] + ext

    def export(self, fmt, fname=None, **options):
        """Export to any format the selected backend supports."""
        dest = self._dest(fname, "." + fmt)
        return self.backend_for(fmt).export(self.fname, dest, fmt=fmt, **options)

    def to_csv(self, fname=None, markers=True, header=True,
               rotation=Quaternions, units=Meters, frame_rate=None, **options):
        """Export the take's tracking data to a CSV file.

        Defaults mirror Motive's own CSV export, which includes marker data --
        note that ``markers`` defaulted to False before 0.3.0, producing a file
        a fraction of the expected size on marker-heavy takes.
        """
        dest = self._dest(fname, ".csv")
        return self.backend_for(_fmt.CSV).export(
            self.fname, dest, fmt=_fmt.CSV, markers=markers, header=header,
            rotation=rotation, units=units, frame_rate=frame_rate, **options)

    def to_avi(self, fname=None):
        """Export the take's video content to an AVI file (Windows/NMotive only)."""
        return self.export(_fmt.AVI, self._dest(fname, ".avi"))

    def to_bvh(self, fname=None):
        """Export skeleton data to BVH (Windows/NMotive only)."""
        return self.export(_fmt.BVH, self._dest(fname, ".bvh"))

    def to_c3d(self, fname=None):
        """Export to C3D (Windows/NMotive only)."""
        return self.export(_fmt.C3D, self._dest(fname, ".c3d"))

    def to_trc(self, fname=None):
        """Export to TRC (Windows/NMotive only)."""
        return self.export(_fmt.TRC, self._dest(fname, ".trc"))

    def to_fbx(self, fname=None, binary=True):
        """Export to FBX (Windows/NMotive only)."""
        fmt = _fmt.FBX_BINARY if binary else _fmt.FBX_ASCII
        return self.export(fmt, self._dest(fname, ".fbx"))

    # -- inspection (native backend, works anywhere) --------------------------

    def document(self):
        """Parse the take with the pure-Python reader and return the document."""
        from .tak import load
        return load(self.fname)

    def __repr__(self):
        return "<Take {!r}>".format(os.path.basename(self.fname))
