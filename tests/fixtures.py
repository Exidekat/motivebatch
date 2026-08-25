"""Synthetic .tak builders so the suite runs on a bare clone.

The real sample take lives in temp/, which is gitignored, so every structural
test builds its own compound file here instead.
"""

import math
import struct

SECTOR = 512
MINI_SECTOR = 64
MINI_CUTOFF = 4096

FREESECT = 0xFFFFFFFF
ENDOFCHAIN = 0xFFFFFFFE
FATSECT = 0xFFFFFFFD

SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def u16str(s):
    """uint16 char count + UTF-16LE payload, as the .tak streams encode text."""
    return struct.pack("<H", len(s)) + s.encode("utf-16-le")


# --- stream builders ---------------------------------------------------------

CHANNEL_MAGIC = 0x4C390AF3
_NCOMP = {"FloatChannel": 1, "Vector3fChannel": 3, "QuaternionChannel": 4}


def build_channels(channels, version=5):
    """``channels`` is a list of ``(type_name, name, [(frame, (v, ...)), ...])``."""
    out = [struct.pack("<IHI", CHANNEL_MAGIC, version, len(channels))]
    for type_name, name, samples in channels:
        n = _NCOMP[type_name]
        out.append(u16str(type_name))
        out.append(b"\x04")
        out.append(u16str(name))
        out.append(bytes(range(16)))                    # type id
        out.append(struct.pack("<%df" % n, *([0.0] * n)))  # per-type default
        out.append(struct.pack("<I", len(samples)))
        for frame, values in samples:
            out.append(struct.pack("<I", frame))
            out.append(struct.pack("<%df" % n, *values))
    return b"".join(out)


def build_nodes(nodes, version=3):
    """``nodes`` is a list of ``(type_name, properties_dict)``."""
    import json
    out = [struct.pack("<B", version), struct.pack("<I", len(nodes))]
    for type_name, props in nodes:
        payload = {"properties": [{"name": k, "value": v} for k, v in props.items()]}
        out.append(u16str(type_name))
        out.append(u16str(json.dumps(payload)))
        out.append(b"\x00" * 16)  # opaque trailer, as Motive writes
    return b"".join(out)


# --- compound file writer ----------------------------------------------------

def build_ole(streams):
    """Assemble ``{name: bytes}`` into a valid OLE2 compound file."""
    large = [(n, d) for n, d in streams.items() if len(d) >= MINI_CUTOFF]
    small = [(n, d) for n, d in streams.items() if len(d) < MINI_CUTOFF]

    sectors = []
    chains = {}

    def alloc(data, key):
        if not data:
            chains[key] = []
            return
        blocks = [data[i:i + SECTOR].ljust(SECTOR, b"\x00")
                  for i in range(0, len(data), SECTOR)]
        start = len(sectors)
        sectors.extend(blocks)
        chains[key] = list(range(start, start + len(blocks)))

    # Mini streams live inside one ministream owned by the root entry.
    mini_blob = b""
    mini_starts = {}
    minifat = []
    for name, data in small:
        first = len(minifat)
        mini_starts[name] = first
        nblocks = max(1, int(math.ceil(len(data) / float(MINI_SECTOR))))
        padded = data.ljust(nblocks * MINI_SECTOR, b"\x00")
        mini_blob += padded
        for i in range(nblocks):
            minifat.append(first + i + 1 if i < nblocks - 1 else ENDOFCHAIN)

    for name, data in large:
        alloc(data, ("stream", name))
    alloc(mini_blob, ("ministream",))
    minifat_bytes = struct.pack("<%dI" % len(minifat), *minifat) if minifat else b""
    alloc(minifat_bytes, ("minifat",))

    # Directory: root, then one entry per stream.
    entries = [("Root Entry", 5, chains[("ministream",)], len(mini_blob))]
    for name, data in large:
        entries.append((name, 2, chains[("stream", name)], len(data)))
    for name, data in small:
        entries.append((name, 2, [mini_starts[name]], len(data)))

    dir_bytes = b""
    for name, kind, chain, size in entries:
        raw = bytearray(128)
        encoded = name.encode("utf-16-le") + b"\x00\x00"
        raw[:len(encoded)] = encoded
        struct.pack_into("<H", raw, 64, len(encoded))
        raw[66] = kind
        raw[67] = 1                                    # black
        struct.pack_into("<i", raw, 68, -1)            # left sibling
        struct.pack_into("<i", raw, 72, -1)            # right sibling
        struct.pack_into("<i", raw, 76, 1 if kind == 5 else -1)  # child
        struct.pack_into("<I", raw, 116, chain[0] if chain else ENDOFCHAIN)
        struct.pack_into("<Q", raw, 120, size)
        dir_bytes += bytes(raw)
    alloc(dir_bytes, ("directory",))

    # Reserve FAT sectors, which themselves occupy sectors.
    per = SECTOR // 4
    n_data = len(sectors)
    n_fat = 1
    while int(math.ceil((n_data + n_fat) / float(per))) > n_fat:
        n_fat += 1

    fat = [FREESECT] * (n_fat * per)
    for chain in chains.values():
        for i, sect in enumerate(chain):
            fat[sect] = chain[i + 1] if i + 1 < len(chain) else ENDOFCHAIN
    for i in range(n_fat):
        fat[n_data + i] = FATSECT

    fat_bytes = struct.pack("<%dI" % len(fat), *fat)
    for i in range(n_fat):
        sectors.append(fat_bytes[i * SECTOR:(i + 1) * SECTOR].ljust(SECTOR, b"\x00"))

    header = bytearray(SECTOR)
    header[0:8] = SIGNATURE
    struct.pack_into("<H", header, 0x18, 0x003E)       # minor version
    struct.pack_into("<H", header, 0x1A, 0x0003)       # major version
    struct.pack_into("<H", header, 0x1C, 0xFFFE)       # little-endian
    struct.pack_into("<H", header, 0x1E, 9)            # 512-byte sectors
    struct.pack_into("<H", header, 0x20, 6)            # 64-byte mini sectors
    struct.pack_into("<I", header, 0x2C, n_fat)
    struct.pack_into("<I", header, 0x30, chains[("directory",)][0])
    struct.pack_into("<I", header, 0x38, MINI_CUTOFF)
    struct.pack_into("<I", header, 0x3C,
                     chains[("minifat",)][0] if minifat else ENDOFCHAIN)
    struct.pack_into("<I", header, 0x40, len(chains[("minifat",)]))
    struct.pack_into("<I", header, 0x44, ENDOFCHAIN)   # no extra DIFAT
    struct.pack_into("<I", header, 0x48, 0)
    for i in range(109):
        struct.pack_into("<I", header, 0x4C + 4 * i,
                         n_data + i if i < n_fat else FREESECT)

    return bytes(header) + b"".join(sectors)


# --- convenience -------------------------------------------------------------

def simple_take(frames=4, rigid_bodies=2, markers=3, frame_rate=120.0):
    """A small but structurally complete take."""
    channels = [("FloatChannel", "SystemLatency", [])]
    nodes = [("TelemetryNode", {})]

    for r in range(rigid_bodies):
        trans = [(f, (float(r), float(f), 0.5)) for f in range(frames)]
        rot = [(f, (0.0, 0.0, 0.0, 1.0)) for f in range(frames)]
        err = [(f, (0.001 * (r + 1),)) for f in range(frames)]
        channels += [("Vector3fChannel", "Translation", trans),
                     ("QuaternionChannel", "Rotation", rot),
                     ("FloatChannel", "MarkerError", err)]
        nodes.append(("RigidBody", {"NodeName": "Body %d" % r, "UserData": str(10 + r)}))

    nodes.append(("CameraNode", {
        "NodeName": "Prime #1",
        "CameraNodeCameraFrameRate": "%.6f" % frame_rate,
        "CameraNodeCameraFrameRateDivisor": "1",
    }))
    channels += [("Vector3fChannel", "Translation", []),
                 ("QuaternionChannel", "Rotation", [])]

    for m in range(markers):
        pos = [(f, (0.1 * m, 0.2 * f, 0.3)) for f in range(frames)]
        channels.append(("Vector3fChannel", "Translation", pos))
        nodes.append(("Marker", {"NodeName": "Marker %03d" % (m + 1)}))

    return build_ole({
        "Channels.dat": build_channels(channels),
        "Nodes.dat": build_nodes(nodes),
        "MetaData.dat": b"\x00" * 64,          # small -> exercises the mini path
    })
