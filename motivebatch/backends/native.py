"""Pure-Python backend.  Standard library only, runs on every platform.

Reads the take's solved channel data directly out of the .tak container.  This
is a best-effort reproduction of Motive's CSV exporter, not a byte-exact one --
see the NMotive backend for that.
"""

from .. import csvwriter
from .. import units as _units
from ..errors import ExportNotSupported
from ..tak import load as _load
from .base import CSV, Backend


class NativeBackend(Backend):
    name = "native"
    formats = (CSV,)

    def describe(self):
        return "native (pure Python, no dependencies; CSV only, best-effort fidelity)"

    def export(self, source, dest, fmt=CSV, markers=True, header=True,
               rotation=_units.Quaternions, units=_units.Meters,
               frame_rate=None, progress=None, **_ignored):
        # bones / quality_stats / nmotive_set are NMotive-only and are ignored
        # here; this reader has no skeleton support.
        self.check(fmt)
        doc = _load(source)
        if not doc.assets:
            raise ExportNotSupported(
                "this take contains no solved rigid bodies or markers; it likely "
                "needs to be reconstructed and solved in Motive first")
        # newline="" so the csv module controls line endings exactly.
        bar = progress
        callback = None
        if bar is not None and getattr(bar, "enabled", False):
            bar.start(doc.frame_count)
            callback = lambda done, total: bar.update(done, total)
        try:
            with open(dest, "w", newline="", encoding="utf-8") as fh:
                csvwriter.write(doc, fh, markers=markers, header=header,
                                rotation=rotation, units=units,
                                frame_rate=frame_rate, progress=callback)
        except BaseException:
            if bar is not None:
                bar.clear()
            raise
        if bar is not None:
            bar.finish()
        return dest

    def take_info(self, source):
        doc = _load(source)
        return {
            "frame_rate": doc.frame_rate,
            "frame_count": doc.frame_count,
            "rigid_bodies": len(doc.rigid_bodies),
            "markers": len(doc.markers),
            "cameras": len(doc.cameras),
        }
