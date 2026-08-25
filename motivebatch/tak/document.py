"""Binds ``Nodes.dat`` assets to their ``Channels.dat`` data.

Motive does not store an explicit node-to-channel link: the channel type ids are
per-type constants, not per-instance handles.  The association is positional --
channels appear in node order, each node consuming a fixed signature of channel
types.  Verified against Motive 3 takes, where the counts reconcile exactly::

    TelemetryNode  -> the leading run of FloatChannels
    RigidBody      -> Translation, Rotation, MarkerError
    CameraNode     -> Translation, Rotation
    Marker         -> Translation
    Constraint     -> (none)
"""

from ..errors import TakFormatError
from . import channels as _ch
from . import nodes as _nd
from .ole import OleFile

CHANNELS_STREAM = "Channels.dat"
NODES_STREAM = "Nodes.dat"


class Asset(object):
    """An exportable asset with its bound channels."""

    __slots__ = ("kind", "name", "node", "translation", "rotation", "error")

    def __init__(self, kind, node, translation=None, rotation=None, error=None):
        self.kind = kind
        self.node = node
        self.name = node.name
        self.translation = translation
        self.rotation = rotation
        self.error = error

    @property
    def id(self):
        """Motive's streaming ID for the asset, when it has one."""
        return self.node.properties.get("UserData")

    @property
    def has_rotation(self):
        return self.rotation is not None and self.rotation.count > 0

    @property
    def sample_count(self):
        for c in (self.translation, self.rotation, self.error):
            if c is not None and c.count:
                return c.count
        return 0

    def __repr__(self):
        return "<Asset {} {!r} n={}>".format(self.kind, self.name, self.sample_count)


class TakDocument(object):
    """A parsed take: assets, channels and frame extent."""

    def __init__(self, data, name=None):
        self.name = name
        self.ole = OleFile(data)
        for required in (CHANNELS_STREAM, NODES_STREAM):
            if not self.ole.has_stream(required):
                raise TakFormatError(
                    "take is missing the {} stream; it may be from an "
                    "unsupported Motive version".format(required))

        self.channels_version, self.channels = _ch.parse(self.ole.read(CHANNELS_STREAM))
        self.nodes_version, self.nodes = _nd.parse(self.ole.read(NODES_STREAM))

        self.telemetry = []
        self.rigid_bodies = []
        self.markers = []
        self.cameras = []
        self._bind()

    # -- binding --------------------------------------------------------------

    def _bind(self):
        chans = self.channels
        i = 0

        def take(expected, node):
            nonlocal i
            if i >= len(chans):
                raise TakFormatError(
                    "take ran out of channels binding {} {!r}".format(node.type_name, node.name))
            c = chans[i]
            if c.type_name != expected:
                raise TakFormatError(
                    "channel {} is {} but {} {!r} expects {}".format(
                        i, c.type_name, node.type_name, node.name, expected))
            i += 1
            return c

        for node in self.nodes:
            t = node.type_name
            if t == "TelemetryNode":
                # Consume the leading run of scalar telemetry channels.
                while i < len(chans) and chans[i].type_name == _ch.FLOAT:
                    self.telemetry.append(chans[i])
                    i += 1
            elif t == "RigidBody":
                tr = take(_ch.VECTOR3F, node)
                rot = take(_ch.QUATERNION, node)
                err = take(_ch.FLOAT, node)
                self.rigid_bodies.append(Asset("RigidBody", node, tr, rot, err))
            elif t == "CameraNode":
                tr = take(_ch.VECTOR3F, node)
                rot = take(_ch.QUATERNION, node)
                self.cameras.append(Asset("Camera", node, tr, rot))
            elif t == "Marker":
                tr = take(_ch.VECTOR3F, node)
                self.markers.append(Asset("Marker", node, tr))
            # Constraint and anything unrecognised own no channels.

        if i != len(chans):
            raise TakFormatError(
                "channel binding consumed {} of {} channels; the take layout is "
                "not understood".format(i, len(chans)))

    # -- frame extent ---------------------------------------------------------

    @property
    def assets(self):
        """Exportable assets in Motive's own ordering."""
        return self.rigid_bodies + self.markers

    @property
    def frame_rate(self):
        """Capture frame rate, read off the camera nodes.

        ``MetaData.dat`` is compressed and not decoded, but every CameraNode
        records the rate it ran at, which is the take's capture rate.
        """
        for node in self.nodes:
            if node.type_name != "CameraNode":
                continue
            rate = node.properties.get("CameraNodeCameraFrameRate")
            divisor = node.properties.get("CameraNodeCameraFrameRateDivisor")
            try:
                rate = float(rate)
                divisor = float(divisor) if divisor else 1.0
            except (TypeError, ValueError):
                continue
            if rate > 0 and divisor > 0:
                return rate / divisor
        return None

    @property
    def frame_count(self):
        best = 0
        for a in self.assets:
            best = max(best, a.sample_count)
        return best

    @property
    def frame_range(self):
        lo, hi = None, None
        for a in self.assets:
            for c in (a.translation, a.rotation, a.error):
                if c is None or not c.count:
                    continue
                r = c.frame_range
                lo = r[0] if lo is None else min(lo, r[0])
                hi = r[1] if hi is None else max(hi, r[1])
        if lo is None:
            return (0, -1)
        return (lo, hi)

    def __repr__(self):
        return "<TakDocument {!r} rigid_bodies={} markers={} frames={}>".format(
            self.name, len(self.rigid_bodies), len(self.markers), self.frame_count)


def load(path):
    """Read and parse a .tak file from disk."""
    import os
    with open(path, "rb") as fh:
        data = fh.read()
    return TakDocument(data, name=os.path.splitext(os.path.basename(path))[0])
