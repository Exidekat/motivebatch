"""Backend-neutral unit and rotation constants.

The original IronPython implementation pulled these straight off the NMotive
enums at import time, which made ``import motivebatch`` fail on any machine
without the DLL.  They are plain values here; each backend translates them into
whatever its own runtime expects.
"""

import itertools
import math

# --- length units ------------------------------------------------------------

Meters = "Meters"
Centimeters = "Centimeters"
Millimeters = "Millimeters"

LENGTH_UNITS = (Meters, Centimeters, Millimeters)

#: Multiplier to convert a value expressed in meters into the given unit.
_FROM_METERS = {Meters: 1.0, Centimeters: 100.0, Millimeters: 1000.0}


def scale_from_meters(units):
    """Return the factor converting meters into ``units``."""
    try:
        return _FROM_METERS[units]
    except KeyError:
        raise ValueError("unknown length unit: {!r}".format(units))


# --- rotation types ----------------------------------------------------------

Quaternions = "Quaternion"

#: All six Euler orders, exposed as module-level names (XYZ, XZY, ... ZYX).
EULER_ORDERS = tuple("".join(o) for o in itertools.permutations("XYZ"))
for _order in EULER_ORDERS:
    globals()[_order] = _order
del _order

ROTATION_TYPES = (Quaternions,) + EULER_ORDERS


def quaternion_to_euler(x, y, z, w, order):
    """Convert a quaternion to intrinsic Euler angles in degrees.

    ``order`` is one of the six permutations of ``"XYZ"`` and names the axes in
    application order, matching Motive's own convention.
    """
    if order not in EULER_ORDERS:
        raise ValueError("unknown rotation order: {!r}".format(order))

    # Normalise defensively; exported quaternions are unit-norm but gap-filled
    # frames occasionally are not.
    n = math.sqrt(x * x + y * y + z * z + w * w)
    if n == 0.0:
        return (0.0, 0.0, 0.0)
    x, y, z, w = x / n, y / n, z / n, w / n

    # Rotation matrix (column-vector convention).
    m = (
        (1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)),
        (2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)),
        (2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)),
    )

    i, j, k = ("XYZ".index(c) for c in order)
    parity = (j == (i + 1) % 3)
    sign = 1.0 if parity else -1.0

    # Extract the middle angle first; it determines whether we are at a
    # gimbal-lock singularity.
    sy = m[i][k] * sign
    sy = max(-1.0, min(1.0, sy))
    b = math.asin(sy)

    if abs(sy) < 1.0 - 1e-9:
        a = math.atan2(-m[j][k] * sign, m[k][k])
        c = math.atan2(-m[i][j] * sign, m[i][i])
    else:
        # Degenerate: fold the two free angles into one.
        a = math.atan2(m[k][j] * sign, m[j][j])
        c = 0.0

    return tuple(math.degrees(v) for v in (a, b, c))
