# The Motive `.tak` format

Reverse-engineered from Motive 3 takes and verified byte-exact: parsing the
sample take consumes every byte of `Channels.dat` and recovers exactly the node
count `Nodes.dat` declares. This documents what `motivebatch/tak/` implements.

## Container

A `.tak` is an **OLE2 Compound File** (signature `D0 CF 11 E0 A1 B1 1A E1`) —
the same container as legacy `.doc`/`.xls`. Motive uses 32768-byte sectors with
512-byte mini sectors.

| Stream | Contents |
|---|---|
| `Channels.dat` | solved per-frame data — **this is what a CSV export contains** |
| `Nodes.dat` | asset definitions (rigid bodies, markers, cameras, constraints) |
| `Track 0.trk` | raw point cloud / camera data |
| `Track 1.trk` | small secondary track |
| `MetaData.dat` | compressed; not decoded |
| `Calibration.dat` | compressed; not decoded |

Motive leaves the file's final sector partially written, so a reader must clamp
to each stream's declared size rather than demanding a whole trailing sector.

## Shared primitives

All integers are little-endian. Strings are a `uint16` **character** count
followed by that many UTF-16LE code units — note characters, not bytes.

## `Channels.dat`

```
uint32  magic = 0x4C390AF3
uint16  version            (5 in Motive 3)
uint32  channel_count
channel_count x {
    string   type_name     FloatChannel | Vector3fChannel | QuaternionChannel
    uint8    tag           0x04 in every observed file
    string   name          Translation | Rotation | MarkerError | <telemetry>
    byte[16] type_id       constant per type_name — NOT a per-instance handle
    float    default[C]    C = 1 | 3 | 4, the component count for the type
    uint32   sample_count
    sample_count x {
        uint32 frame
        float  value[C]
    }
}
```

Two details cause almost all failed parses:

1. **The `default[C]` block.** Its size varies with the channel type, so record
   sizes differ between types. Skipping it desynchronises the stream at the
   first `Vector3fChannel` and everything after is garbage.
2. **The frame index comes first** in each sample, not last. Reading
   `x, y, z, frame` instead of `frame, x, y, z` yields plausible-looking floats
   that are silently shifted by one field.

`type_id` is a per-type constant (every `FloatChannel` shares one, every
`Vector3fChannel` another), so it cannot be used to link a channel to a node.

## `Nodes.dat`

```
uint8   version            (3 in Motive 3)
uint32  node_count
node_count x {
    string  type_name      TelemetryNode | RigidBody | Marker | CameraNode | Constraint
    string  payload        JSON
    byte[]  trailer        variable length, not length-prefixed
}
```

The JSON payload is `{"properties": [{"name": ..., "value": ...}, ...]}`.
Useful keys:

| Key | Meaning |
|---|---|
| `NodeName` | asset name as shown in Motive |
| `UserData` | rigid body streaming ID (the CSV `ID` row) |
| `CameraNodeCameraFrameRate` | capture frame rate |
| `CameraNodeCameraFrameRateDivisor` | divisor applied to the above |

The trailer's length is not encoded anywhere, so records are located by
scanning for the next well-formed `(type_name, JSON object)` header. This is
unambiguous because every payload is a JSON object, and it recovers exactly the
declared node count.

Because `MetaData.dat` is compressed, the **camera nodes are the practical
source of the capture frame rate**.

## Binding channels to nodes

There is no explicit link. The association is **positional**: channels appear in
node order, each node consuming a fixed signature.

| Node type | Channels consumed, in order |
|---|---|
| `TelemetryNode` | the leading run of `FloatChannel`s (system/latency stats) |
| `RigidBody` | `Translation`, `Rotation`, `MarkerError` |
| `CameraNode` | `Translation`, `Rotation` |
| `Marker` | `Translation` |
| `Constraint` | none |

Interleaved `Constraint` nodes consume nothing, so a single sequential walk
binds correctly. On the reference take the counts reconcile exactly:

```
 79 Vector3f Translation  =  8 rigid bodies + 60 markers + 11 cameras
 19 Quaternion Rotation   =  8 rigid bodies             + 11 cameras
 28 Float                 = 20 telemetry    +  8 rigid-body MarkerError
                           ----
                            126 channels
```

A reader should treat a leftover or missing channel as a hard error — silently
shifting assets onto the wrong data is far worse than refusing to export.

## Units and conventions

Translations are **meters**; rotations are unit quaternions in `(X, Y, Z, W)`
order. Both match what Motive's CSV exporter emits with its default settings.
