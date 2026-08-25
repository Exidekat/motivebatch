"""Read-only OLE2 / Compound File Binary reader.

Motive stores a .tak as an OLE2 compound document whose streams hold the actual
take data.  Only the subset needed to enumerate and read streams is implemented,
using nothing outside the standard library.
"""

import struct

from ..errors import TakFormatError

SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

MAXREGSECT = 0xFFFFFFFA
DIFSECT = 0xFFFFFFFC
FATSECT = 0xFFFFFFFD
ENDOFCHAIN = 0xFFFFFFFE
FREESECT = 0xFFFFFFFF

_STGTY_STORAGE = 1
_STGTY_STREAM = 2
_STGTY_ROOT = 5


class DirEntry(object):
    """One directory entry: a storage, a stream, or the root."""

    __slots__ = ("name", "kind", "start", "size")

    def __init__(self, name, kind, start, size):
        self.name = name
        self.kind = kind
        self.start = start
        self.size = size

    @property
    def is_stream(self):
        return self.kind == _STGTY_STREAM

    def __repr__(self):
        return "<DirEntry {!r} kind={} size={}>".format(self.name, self.kind, self.size)


class OleFile(object):
    """Parsed compound file.  Construct from ``bytes``, then :meth:`read`."""

    def __init__(self, data):
        if len(data) < 512 or data[:8] != SIGNATURE:
            raise TakFormatError("not an OLE2 compound file (bad signature)")
        self._d = data

        sector_shift, mini_shift = struct.unpack_from("<HH", data, 0x1E)
        self.sector_size = 1 << sector_shift
        self.mini_sector_size = 1 << mini_shift
        if self.sector_size < 128 or self.mini_sector_size < 16:
            raise TakFormatError("implausible sector sizes in compound file header")

        self.mini_cutoff = struct.unpack_from("<I", data, 0x38)[0]
        dir_start = struct.unpack_from("<I", data, 0x30)[0]
        minifat_start = struct.unpack_from("<I", data, 0x3C)[0]
        difat_start, difat_count = struct.unpack_from("<II", data, 0x44)

        self._fat = self._read_fat(difat_start, difat_count)
        self._minifat = self._read_chain_as_uint32(minifat_start)

        self.entries = self._read_directory(dir_start)
        self._by_name = {}
        root = None
        for e in self.entries:
            if e.kind == _STGTY_ROOT:
                root = e
            elif e.is_stream:
                # Later duplicates would be ambiguous; first wins.
                self._by_name.setdefault(e.name, e)
        if root is None:
            raise TakFormatError("compound file has no root entry")
        self._root = root
        self._ministream = None

    # -- sector plumbing ------------------------------------------------------

    def _sector_offset(self, sect):
        # The 512-byte header occupies the whole of sector -1, so data sectors
        # start one full sector in -- which matters for the 4K/32K sector sizes
        # Motive actually uses.
        return (sect + 1) * self.sector_size

    def _sector(self, sect):
        o = self._sector_offset(sect)
        if o >= len(self._d):
            raise TakFormatError(
                "truncated compound file: sector {} starts past end of file".format(sect))
        chunk = self._d[o:o + self.sector_size]
        if len(chunk) < self.sector_size:
            # Motive leaves the final sector partially written; the per-stream
            # size clamps the excess, so pad rather than reject the file.
            chunk = chunk + b"\x00" * (self.sector_size - len(chunk))
        return chunk

    def _read_fat(self, difat_start, difat_count):
        per = self.sector_size // 4
        difat = list(struct.unpack_from("<109I", self._d, 0x4C))
        sect = difat_start
        seen = set()
        while sect <= MAXREGSECT and difat_count:
            if sect in seen:
                raise TakFormatError("cyclic DIFAT chain")
            seen.add(sect)
            block = self._sector(sect)
            difat.extend(struct.unpack_from("<%dI" % (per - 1), block, 0))
            sect = struct.unpack_from("<I", block, (per - 1) * 4)[0]

        fat = []
        for fs in difat:
            if fs > MAXREGSECT:
                continue
            fat.extend(struct.unpack_from("<%dI" % per, self._sector(fs), 0))
        return fat

    def _chain(self, start):
        """Sector numbers making up a stream, following the FAT."""
        out = []
        sect = start
        seen = set()
        while sect <= MAXREGSECT:
            if sect in seen:
                raise TakFormatError("cyclic sector chain at {}".format(sect))
            if sect >= len(self._fat):
                raise TakFormatError("sector {} outside FAT".format(sect))
            seen.add(sect)
            out.append(sect)
            sect = self._fat[sect]
        return out

    def _read_chain_as_uint32(self, start):
        per = self.sector_size // 4
        vals = []
        for s in self._chain(start):
            vals.extend(struct.unpack_from("<%dI" % per, self._sector(s), 0))
        return vals

    def _read_directory(self, dir_start):
        entries = []
        for sect in self._chain(dir_start):
            block = self._sector(sect)
            for i in range(self.sector_size // 128):
                raw = block[i * 128:(i + 1) * 128]
                name_len = struct.unpack_from("<H", raw, 64)[0]
                kind = raw[66]
                if name_len == 0 or kind not in (_STGTY_STORAGE, _STGTY_STREAM, _STGTY_ROOT):
                    continue
                name = raw[:max(0, name_len - 2)].decode("utf-16-le", "replace")
                start, size = struct.unpack_from("<I", raw, 116)[0], struct.unpack_from("<Q", raw, 120)[0]
                entries.append(DirEntry(name, kind, start, size))
        return entries

    # -- public API -----------------------------------------------------------

    @property
    def stream_names(self):
        return sorted(self._by_name)

    def has_stream(self, name):
        return name in self._by_name

    def read(self, name):
        """Return the full contents of stream ``name`` as ``bytes``."""
        try:
            e = self._by_name[name]
        except KeyError:
            raise TakFormatError("no such stream: {!r}".format(name))

        if e.size < self.mini_cutoff:
            return self._read_mini(e)
        buf = bytearray()
        for s in self._chain(e.start):
            buf += self._sector(s)
        return bytes(buf[:e.size])

    def _read_mini(self, e):
        if self._ministream is None:
            buf = bytearray()
            for s in self._chain(self._root.start):
                buf += self._sector(s)
            self._ministream = bytes(buf)
        out = bytearray()
        sect = e.start
        seen = set()
        msz = self.mini_sector_size
        while sect <= MAXREGSECT:
            if sect in seen:
                raise TakFormatError("cyclic mini chain")
            seen.add(sect)
            out += self._ministream[sect * msz:(sect + 1) * msz]
            if sect >= len(self._minifat):
                break
            sect = self._minifat[sect]
        return bytes(out[:e.size])
