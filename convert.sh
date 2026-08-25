#!/usr/bin/env sh
# ---------------------------------------------------------------------------
#  motivebatch - convert Motive .tak files to .csv
#
#      ./convert.sh Take.tak
#      ./convert.sh /path/to/NMotive.dll Take.tak
#
#  A path to NMotive.dll is accepted anywhere in the arguments.  On Windows it
#  is used; on macOS and Linux it is ignored, because NMotive.dll is a
#  mixed-mode C++/CLI assembly that only the Windows CLR can load.  The
#  built-in reader handles CSV on every platform with no dependencies.
#
#  Converted .csv files are written to the Desktop.
# ---------------------------------------------------------------------------
set -eu

REPO=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
VENV="$REPO/.venv"
PYTHONPATH="$REPO${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONPATH

if [ -x "$VENV/bin/python" ]; then
    PYEXE="$VENV/bin/python"
elif [ -x "$VENV/Scripts/python.exe" ]; then
    PYEXE="$VENV/Scripts/python.exe"
elif command -v python3 >/dev/null 2>&1; then
    PYEXE=python3
elif command -v python >/dev/null 2>&1; then
    PYEXE=python
else
    cat >&2 <<'MSG'

  Python 3 was not found.

    macOS   brew install python3     (or install from python.org)
    Ubuntu  sudo apt install python3

MSG
    exit 1
fi

if [ "$#" -eq 0 ]; then
    cat >&2 <<'MSG'

  motivebatch - Motive .tak to .csv

      ./convert.sh Take.tak
      ./convert.sh /path/to/NMotive.dll Take.tak

  Options: --markers  --units mm  --rotation XYZ  --beside-input
           --info  --list-backends

MSG
    exit 2
fi

exec "$PYEXE" -m motivebatch "$@"
