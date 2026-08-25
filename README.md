# motivebatch

Convert OptiTrack Motive `.tak` files to CSV — on Windows, macOS and Linux.

Clone it and run it. No IronPython, no build step, and nothing to `pip install`
for the common case.

```bash
git clone https://github.com/Exidekat/motivebatch
cd motivebatch
./convert.sh "My Take.tak"          # macOS / Linux
convert.bat "My Take.tak"           # Windows — or drag .tak files onto it
```

The `.csv` lands on your Desktop with the same name as the take.

## How it works

There are two backends, and the right one is chosen automatically.

| | Windows + Motive | Any OS, no Motive |
|---|---|---|
| **Backend** | `nmotive` — Motive's own exporter, via pythonnet | `native` — pure Python, standard library only |
| **CSV** | byte-for-byte Motive output | faithful best-effort reproduction |
| **AVI, BVH, C3D, TRC, FBX** | yes | not available |
| **Setup** | venv + pythonnet, bootstrapped on first run | none |

`NMotive.dll` is a mixed-mode C++/CLI assembly: 25 MB of native x86-64 code
behind an IJW native entry point. Only the Windows CLR can load such an
assembly — Mono and .NET on Linux/macOS cannot, no matter how it is packaged.
That is why the portable backend exists, and why it reads the `.tak` container
directly rather than wrapping the SDK. See [docs/TAK_FORMAT.md](docs/TAK_FORMAT.md)
for the format it decodes.

### Finding NMotive.dll

Searched in order: an explicit path → `$NMOTIVE_DLL` → the saved config file →
the standard Motive install directories → next to this checkout. If none of
those turn it up and NMotive is genuinely required, you are asked once, and the
answer is remembered.

```bash
convert.bat "C:\Program Files\OptiTrack\Motive\assemblies\x64\NMotive.dll" Take.tak
```

A `.dll` argument is recognised anywhere in the argument list. On macOS and
Linux it is accepted and ignored, so the same command line works everywhere.

> NMotive depends on ~20 sibling DLLs (Qt among them) from the Motive install.
> A lone copied-out `NMotive.dll` will usually fail to load; point at the one in
> the real install directory.

## Command line

```
convert.sh [options] <take.tak> [take2.tak ...] [NMotive.dll]

  --markers               include individual marker positions
  --units mm|cm|meters    length units (default: meters)
  --rotation XYZ|...      quaternion (default) or any of the six Euler orders
  --format csv|avi|...    export format (non-CSV needs Windows + Motive)
  --beside-input          write next to the .tak instead of the Desktop
  --output-dir DIR        write everywhere else
  --overwrite             replace instead of adding a " (1)" suffix
  --info                  describe the take without exporting
  --list-backends         show what can run here, and why
  --backend native        force a backend
  -v, --verbose           explain the backend choice
```

Inspecting a take works on any machine:

```
$ ./convert.sh --info "My Take.tak"
  frames        1200 (0..1199)
  frame rate    120.0
  rigid bodies  4
  markers       32
  cameras       8
    rigid body  Example Body                 id=4
```

## Python API

```python
from motivebatch import Take, Millimeters, XYZ

take = Take('myfile.tak')
take.to_csv('myfile.csv', markers=True, units=Millimeters, rotation=XYZ)

print(take.backend_name, take.frame_rate, take.frame_count)
```

`import motivebatch` works with no DLL present — units and rotation constants
are plain values, translated per-backend. On Windows with Motive installed,
`to_avi()`, `to_bvh()`, `to_c3d()`, `to_trc()` and `to_fbx()` are available too;
elsewhere they raise a clear `ExportNotSupported`.

For direct access to the parsed take:

```python
doc = take.document()
for rb in doc.rigid_bodies:
    for frame, (x, y, z) in rb.translation.samples():
        ...
```

## Requirements

Python 3.8+. That is the whole list for CSV on any platform. `pythonnet` is
installed automatically into a local `.venv/`, and only when a Motive install
is actually detected.

## Tests

```bash
python3 -m unittest discover -s tests -t .
```

The suite builds its own synthetic `.tak` files, so it runs on a bare clone.
Dropping a real take into `temp/` enables the integration tests as well.

## Limitations

- The portable backend exports **CSV only**, and reads **solved** take data. A
  take that still needs reconstruct/auto-label/solve must go through Motive.
- Its CSV header block is modelled on Motive's, not diffed against it. Use the
  NMotive backend when exact fidelity matters.
- `MetaData.dat` and `Calibration.dat` are compressed and not decoded; the
  capture frame rate is recovered from the camera nodes instead.

## License

MIT.
