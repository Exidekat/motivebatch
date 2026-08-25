"""CSV emission for the pure-Python backend.

Mirrors the shape of Motive's own CSV exporter -- a metadata line, the stacked
type/name/ID/measure/axis header rows, then one row per frame.  The NMotive
backend is the source of truth for byte-exact output; this is a faithful
best-effort reproduction for machines that cannot load the DLL.
"""

import csv

from . import units as _units
from .tak import channels as _ch

#: Version string Motive stamps on its CSV exports.
FORMAT_VERSION = "1.23"

_QUAT_AXES = ("X", "Y", "Z", "W")
_POS_AXES = ("X", "Y", "Z")


def _fmt(v):
    return "" if v is None else "%.6f" % v


class ColumnGroup(object):
    """One asset's contiguous block of columns, with its samples indexed."""

    __slots__ = ("asset", "kind", "measures", "pos", "rot", "err")

    def __init__(self, asset, kind, measures):
        self.asset = asset
        self.kind = kind
        self.measures = measures  # list of (measure_name, axes tuple)
        # Index each bound channel once; per-frame dict lookups beat rescanning.
        self.pos = asset.translation.by_frame() if asset.translation is not None else {}
        self.rot = asset.rotation.by_frame() if asset.rotation is not None else {}
        self.err = asset.error.by_frame() if asset.error is not None else {}

    @property
    def width(self):
        return sum(len(axes) for _, axes in self.measures)


def _plan(doc, markers, rotation):
    """Build the column layout for the requested export."""
    groups = []
    rot_axes = _QUAT_AXES if rotation == _units.Quaternions else _POS_AXES
    for rb in doc.rigid_bodies:
        measures = [("Rotation", rot_axes), ("Position", _POS_AXES),
                    ("Mean Marker Error", ("",))]
        groups.append(ColumnGroup(rb, "Rigid Body", measures))
    if markers:
        for m in doc.markers:
            groups.append(ColumnGroup(m, "Marker", [("Position", _POS_AXES)]))
    return groups


def _asset_row_values(group, frame, rotation, scale):
    """Values for one asset at one frame, in column order."""
    out = []
    for measure, axes in group.measures:
        if measure == "Rotation":
            s = group.rot.get(frame)
            if s is None:
                out.extend([None] * len(axes))
            elif rotation == _units.Quaternions:
                out.extend(s)
            else:
                out.extend(_units.quaternion_to_euler(s[0], s[1], s[2], s[3], rotation))
        elif measure == "Position":
            s = group.pos.get(frame)
            if s is None:
                out.extend([None] * len(axes))
            else:
                out.extend(v * scale for v in s)
        else:  # Mean Marker Error
            s = group.err.get(frame)
            out.append(None if s is None else s[0])
    return out


def write(doc, stream, markers=True, header=True,
          rotation=_units.Quaternions, units=_units.Meters, frame_rate=None,
          progress=None):
    """Write ``doc`` as CSV into the text ``stream``."""
    if rotation not in _units.ROTATION_TYPES:
        raise ValueError("unknown rotation type: {!r}".format(rotation))
    scale = _units.scale_from_meters(units)
    rate = frame_rate or doc.frame_rate or 0.0

    groups = _plan(doc, markers, rotation)
    w = csv.writer(stream, lineterminator="\r\n")
    first, last = doc.frame_range
    total = doc.frame_count

    if header:
        w.writerow([
            "Format Version", FORMAT_VERSION,
            "Take Name", doc.name or "",
            "Capture Frame Rate", "%.6f" % rate,
            "Export Frame Rate", "%.6f" % rate,
            "Capture Start Frame", first,
            "Total Frames in Take", total,
            "Total Exported Frames", total,
            "Rotation Type", rotation,
            "Length Units", units,
            "Coordinate Space", "Global",
        ])
        w.writerow([])
        w.writerow([])

        type_row, name_row, id_row, measure_row, axis_row = [], [], [], [], []
        for row in (type_row, name_row, id_row, measure_row):
            row.extend(["", ""])
        axis_row.extend(["Frame", "Time (Seconds)"])
        for g in groups:
            for measure, axes in g.measures:
                for ax in axes:
                    type_row.append(g.kind)
                    name_row.append(g.asset.name or "")
                    id_row.append(g.asset.id or "")
                    measure_row.append(measure)
                    axis_row.append(ax)
        for row in (type_row, name_row, id_row, measure_row, axis_row):
            w.writerow(row)

    period = (1.0 / rate) if rate else 0.0
    span = last - first + 1
    if progress is not None:
        progress(0, span)
    for i, frame in enumerate(range(first, last + 1)):
        row = [frame, "%.6f" % (frame * period)]
        for g in groups:
            row.extend(_fmt(v) for v in _asset_row_values(g, frame, rotation, scale))
        w.writerow(row)
        # The bar throttles by time as well; this just keeps the call cheap.
        if progress is not None and not (i & 0x3F):
            progress(i + 1, span)
    if progress is not None:
        progress(span, span)
