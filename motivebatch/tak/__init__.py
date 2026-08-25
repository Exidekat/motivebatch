"""Pure-Python reader for Motive .tak files (standard library only)."""

from .document import Asset, TakDocument, load
from .ole import OleFile

__all__ = ["Asset", "TakDocument", "load", "OleFile"]
