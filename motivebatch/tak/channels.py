"""Decoder for the ``Channels.dat`` stream -- the solved, per-frame take data.

Stream layout, reverse-engineered and verified byte-exact against Motive 3
exports::

    uint32  magic = 0x4C390AF3
    uint16  version
    uint32  channel_count
    channel_count x {
        string  type_name        # FloatChannel | Vector3fChannel | QuaternionChannel
        uint8   tag              # always 0x04 in observed files
        string  name             # Translation | Rotation | MarkerError | <telemetry>
        bytes16 type_id          # constant per type_name, not per instance
        float   default[C]       # C = component count for the type
        uint32  sample_count
        sample_count x { uint32 frame; float value[C] }
    }

The per-type ``default`` block is what makes the record sizes differ between
channel types; missing it is why a naive parse desynchronises after the first
Vector3f channel.
"""

from ..errors import TakFormatError
from .records import Reader

MAGIC = 0x4C390AF3

FLOAT = "FloatChannel"
VECTOR3F = "Vector3fChannel"
QUATERNION = "QuaternionChannel"

#: type name -> number of float components per sample
COMPONENTS = {FLOAT: 1, VECTOR3F: 3, QUATERNION: 4}

#: Channel names Motive uses for solved asset data, as opposed to telemetry.
TRANSLATION = "Translation"
ROTATION = "Rotation"
MARKER_ERROR = "MarkerError"


class Channel(object):
    """A single channel.  Samples are decoded lazily and then cached."""

    __slots__ = ("type_name", "name", "type_id", "default", "count",
                 "_buf", "_off", "_ncomp", "_samples")

    def __init__(self, type_name, name, type_id, default, count, buf, off):
        self.type_name = type_name
        self.name = name
        self.type_id = type_id
        self.default = default
        self.count = count
        self._buf = buf
        self._off = off
        self._ncomp = COMPONENTS[type_name]
        self._samples = None

    @property
    def components(self):
        return self._ncomp

    @property
    def stride(self):
        return 4 + 4 * self._ncomp

    def samples(self):
        """List of ``(frame, (v0, ...))`` pairs, in file order."""
        if self._samples is None:
            import struct
            out = []
            stride = self.stride
            fmt = "<I%df" % self._ncomp
            unpack = struct.Struct(fmt).unpack_from
            buf, off = self._buf, self._off
            for i in range(self.count):
                rec = unpack(buf, off + i * stride)
                out.append((rec[0], rec[1:]))
            self._samples = out
        return self._samples

    def by_frame(self):
        """``{frame: (v0, ...)}`` for random access."""
        return dict(self.samples())

    @property
    def frame_range(self):
        """``(first, last)`` frame numbers, or ``None`` when empty."""
        s = self.samples()
        if not s:
            return None
        return (s[0][0], s[-1][0])

    def __repr__(self):
        return "<Channel {} {!r} n={}>".format(self.type_name, self.name, self.count)


def parse(data):
    """Parse a ``Channels.dat`` payload into a list of :class:`Channel`."""
    r = Reader(data)
    magic = r.u32()
    if magic != MAGIC:
        raise TakFormatError(
            "Channels.dat: bad magic 0x{:08X} (expected 0x{:08X})".format(magic, MAGIC))
    version = r.u16()
    count = r.u32()

    channels = []
    for i in range(count):
        type_name = r.string()
        if type_name not in COMPONENTS:
            raise TakFormatError(
                "Channels.dat: unknown channel type {!r} at record {}".format(type_name, i))
        ncomp = COMPONENTS[type_name]
        tag = r.u8()
        name = r.string()
        type_id = r.bytes(16)
        default = r.floats(ncomp)
        n = r.u32()

        stride = 4 + 4 * ncomp
        if n * stride > r.remaining:
            raise TakFormatError(
                "Channels.dat: record {} ({!r}) claims {} samples but only {} bytes remain"
                .format(i, name, n, r.remaining))
        off = r.pos
        r.skip(n * stride)
        channels.append(Channel(type_name, name, type_id, default, n, data, off))

    if r.remaining:
        raise TakFormatError(
            "Channels.dat: {} trailing bytes after {} records".format(r.remaining, count))
    return version, channels
