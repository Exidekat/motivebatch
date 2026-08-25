"""Common interface every export backend implements."""

from ..errors import ExportNotSupported

CSV = "csv"
AVI = "avi"
BVH = "bvh"
C3D = "c3d"
TRC = "trc"
FBX_ASCII = "fbxascii"
FBX_BINARY = "fbxbinary"

ALL_FORMATS = (CSV, AVI, BVH, C3D, TRC, FBX_ASCII, FBX_BINARY)


class Backend(object):
    """Converts a .tak into an export format.

    Subclasses declare which formats they support and implement :meth:`export`.
    """

    #: Short identifier used in messages and the ``--backend`` flag.
    name = "base"

    #: Formats this backend can produce.
    formats = ()

    def supports(self, fmt):
        return fmt in self.formats

    def check(self, fmt):
        if not self.supports(fmt):
            raise ExportNotSupported(
                "the {} backend cannot export {}; supported here: {}".format(
                    self.name, fmt.upper(), ", ".join(f.upper() for f in self.formats) or "nothing"))

    def describe(self):
        """One-line human description, used by ``--list-backends``."""
        return self.name

    def export(self, source, dest, fmt=CSV, **options):
        raise NotImplementedError

    def take_info(self, source):
        """Return ``{"frame_rate": float|None, "frame_count": int|None}``."""
        return {"frame_rate": None, "frame_count": None}
