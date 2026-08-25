"""motivebatch -- convert OptiTrack Motive .tak files to CSV and other formats.

Works on Windows, macOS and Linux.  On Windows with Motive installed it drives
Motive's own NMotive exporter; everywhere else it falls back to a pure-Python
reader that needs nothing beyond the standard library.
"""

from .errors import (BackendUnavailable, ExportNotSupported, MotiveBatchError,
                     TakFormatError)
from .take import Take
from .units import (EULER_ORDERS, Centimeters, Meters, Millimeters,
                    Quaternions, quaternion_to_euler, scale_from_meters)

# The six Euler orders as module-level names: XYZ, XZY, YXZ, YZX, ZXY, ZYX.
for _o in EULER_ORDERS:
    globals()[_o] = _o
del _o

__version__ = "0.2.0"

__all__ = [
    "Take",
    "Meters", "Centimeters", "Millimeters",
    "Quaternions", "EULER_ORDERS",
    "quaternion_to_euler", "scale_from_meters",
    "MotiveBatchError", "TakFormatError", "BackendUnavailable", "ExportNotSupported",
    "__version__",
] + list(EULER_ORDERS)
