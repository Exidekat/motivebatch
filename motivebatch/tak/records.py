"""Primitives shared by the .tak binary streams.

Every stream Motive writes uses the same two building blocks: little-endian
scalars, and strings stored as a uint16 character count followed by UTF-16LE
code units.
"""

import struct

from ..errors import TakFormatError


class Reader(object):
    """A cursor over a bytes buffer with just the reads the .tak format needs."""

    __slots__ = ("data", "pos")

    def __init__(self, data, pos=0):
        self.data = data
        self.pos = pos

    def __len__(self):
        return len(self.data)

    @property
    def remaining(self):
        return len(self.data) - self.pos

    def _need(self, n):
        if self.pos + n > len(self.data):
            raise TakFormatError(
                "unexpected end of stream: wanted {} bytes at offset {}, {} remain".format(
                    n, self.pos, self.remaining))

    def skip(self, n):
        self._need(n)
        self.pos += n

    def bytes(self, n):
        self._need(n)
        out = self.data[self.pos:self.pos + n]
        self.pos += n
        return out

    def u8(self):
        self._need(1)
        v = self.data[self.pos]
        self.pos += 1
        return v

    def u16(self):
        self._need(2)
        v = struct.unpack_from("<H", self.data, self.pos)[0]
        self.pos += 2
        return v

    def u32(self):
        self._need(4)
        v = struct.unpack_from("<I", self.data, self.pos)[0]
        self.pos += 4
        return v

    def u64(self):
        self._need(8)
        v = struct.unpack_from("<Q", self.data, self.pos)[0]
        self.pos += 8
        return v

    def floats(self, n):
        self._need(4 * n)
        v = struct.unpack_from("<%df" % n, self.data, self.pos)
        self.pos += 4 * n
        return v

    def string(self):
        """uint16 character count, then that many UTF-16LE code units."""
        n = self.u16()
        raw = self.bytes(2 * n)
        try:
            return raw.decode("utf-16-le")
        except UnicodeDecodeError:
            raise TakFormatError("invalid UTF-16 string at offset {}".format(self.pos - 2 * n))
