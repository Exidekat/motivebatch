"""Decoder for the ``Nodes.dat`` stream -- the take's asset definitions.

Layout::

    uint8   version
    uint32  node_count
    node_count x {
        string  type_name    # TelemetryNode | RigidBody | Marker | CameraNode | Constraint
        string  payload      # JSON, UTF-16LE
        bytes   trailer      # variable-length; size depends on node type
    }

The trailer holds binary state that Motive does not surface through the CSV
exporter, and its length is not encoded up front.  Rather than guess, records
are located by scanning for the next well-formed ``(type_name, json)`` header,
which is unambiguous because every payload is a JSON object.
"""

import json
import struct

from ..errors import TakFormatError

#: Node types that own per-frame channels, and the channels they own in order.
CHANNEL_SIGNATURES = {
    "RigidBody": ("Vector3fChannel", "QuaternionChannel", "FloatChannel"),
    "CameraNode": ("Vector3fChannel", "QuaternionChannel"),
    "Marker": ("Vector3fChannel",),
    "Constraint": (),
}


class Node(object):
    """One asset from ``Nodes.dat``."""

    __slots__ = ("type_name", "payload", "properties", "offset")

    def __init__(self, type_name, payload, offset):
        self.type_name = type_name
        self.payload = payload
        self.offset = offset
        self.properties = _flatten(payload)

    @property
    def name(self):
        return self.properties.get("NodeName")

    def __repr__(self):
        return "<Node {} {!r}>".format(self.type_name, self.name)


def _flatten(payload):
    """Turn ``{"properties": [{"name": n, "value": v}, ...]}`` into a dict."""
    out = {}
    if not isinstance(payload, dict):
        return out
    for prop in payload.get("properties", []) or []:
        if isinstance(prop, dict) and "name" in prop:
            out[prop["name"]] = prop.get("value")
    return out


def _try_header(data, p, limit):
    """If a ``(type_name, json)`` header starts at ``p``, return its parts."""
    if p + 4 > limit:
        return None
    n = struct.unpack_from("<H", data, p)[0]
    if not (3 <= n <= 64) or p + 2 + 2 * n + 2 > limit:
        return None
    try:
        type_name = data[p + 2:p + 2 + 2 * n].decode("utf-16-le")
    except UnicodeDecodeError:
        return None
    if not (type_name.isidentifier() and type_name[0].isupper()):
        return None
    q = p + 2 + 2 * n
    m = struct.unpack_from("<H", data, q)[0]
    end = q + 2 + 2 * m
    if end > limit:
        return None
    try:
        text = data[q + 2:q + 2 + 2 * m].decode("utf-16-le")
    except UnicodeDecodeError:
        return None
    stripped = text.strip()
    if not (stripped.startswith("{") and stripped.endswith("}")):
        return None
    return type_name, text, end


def parse(data):
    """Parse a ``Nodes.dat`` payload into a list of :class:`Node`."""
    if len(data) < 5:
        raise TakFormatError("Nodes.dat: stream too short")
    version = data[0]
    count = struct.unpack_from("<I", data, 1)[0]
    limit = len(data)

    nodes = []
    p = 5
    while len(nodes) < count and p < limit:
        hit = _try_header(data, p, limit)
        if hit is None:
            p += 1
            continue
        type_name, text, end = hit
        try:
            payload = json.loads(text)
        except ValueError:
            payload = {}
        nodes.append(Node(type_name, payload, p))
        p = end

    if len(nodes) != count:
        raise TakFormatError(
            "Nodes.dat: header declares {} nodes but {} were recovered".format(count, len(nodes)))
    return version, nodes
