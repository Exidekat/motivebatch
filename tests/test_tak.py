"""Structural tests for the pure-Python .tak reader."""

import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fixtures  # noqa: E402

from motivebatch.errors import TakFormatError  # noqa: E402
from motivebatch.tak import TakDocument, OleFile  # noqa: E402
from motivebatch.tak import channels as ch  # noqa: E402
from motivebatch.tak import nodes as nd  # noqa: E402


class TestOle(unittest.TestCase):
    def test_round_trips_large_and_mini_streams(self):
        big = bytes(range(256)) * 40          # >= 4096, a regular stream
        tiny = b"hello mini stream"           # < 4096, lives in the ministream
        data = fixtures.build_ole({"Big.dat": big, "Tiny.dat": tiny})
        ole = OleFile(data)
        self.assertEqual(ole.stream_names, ["Big.dat", "Tiny.dat"])
        self.assertEqual(ole.read("Big.dat"), big)
        self.assertEqual(ole.read("Tiny.dat"), tiny)

    def test_rejects_non_compound_file(self):
        with self.assertRaises(TakFormatError):
            OleFile(b"not an OLE file" * 100)

    def test_missing_stream_names_itself(self):
        ole = OleFile(fixtures.build_ole({"A.dat": b"x" * 5000}))
        with self.assertRaises(TakFormatError) as cm:
            ole.read("Nope.dat")
        self.assertIn("Nope.dat", str(cm.exception))

    def test_tolerates_short_final_sector(self):
        # Motive leaves the last sector partially written; the stream size
        # clamps the excess, so this must parse rather than raise.
        data = fixtures.build_ole({"A.dat": b"x" * 5000})
        ole = OleFile(data[:-200])
        self.assertEqual(ole.read("A.dat"), b"x" * 5000)


class TestChannels(unittest.TestCase):
    def test_parses_each_channel_type(self):
        raw = fixtures.build_channels([
            ("FloatChannel", "MarkerError", [(0, (1.5,)), (1, (2.5,))]),
            ("Vector3fChannel", "Translation", [(0, (1.0, 2.0, 3.0))]),
            ("QuaternionChannel", "Rotation", [(7, (0.0, 0.0, 0.0, 1.0))]),
        ])
        version, chans = ch.parse(raw)
        self.assertEqual(version, 5)
        self.assertEqual([c.type_name for c in chans],
                         ["FloatChannel", "Vector3fChannel", "QuaternionChannel"])
        self.assertEqual([c.components for c in chans], [1, 3, 4])
        self.assertEqual(chans[0].samples(), [(0, (1.5,)), (1, (2.5,))])
        self.assertEqual(chans[1].by_frame()[0], (1.0, 2.0, 3.0))
        self.assertEqual(chans[2].frame_range, (7, 7))

    def test_empty_channel_has_no_samples(self):
        _, chans = ch.parse(fixtures.build_channels([("FloatChannel", "FinalFPS", [])]))
        self.assertEqual(chans[0].count, 0)
        self.assertEqual(chans[0].samples(), [])
        self.assertIsNone(chans[0].frame_range)

    def test_per_type_default_block_keeps_records_aligned(self):
        # A Vector3f record carries a 12-byte default; ignoring it desynchronises
        # every following record, which is the bug this layout encodes.
        raw = fixtures.build_channels([
            ("Vector3fChannel", "Translation", [(0, (1.0, 2.0, 3.0))]),
            ("FloatChannel", "MarkerError", [(0, (9.0,))]),
        ])
        _, chans = ch.parse(raw)
        self.assertEqual(chans[1].name, "MarkerError")
        self.assertEqual(chans[1].samples(), [(0, (9.0,))])

    def test_bad_magic_is_reported(self):
        raw = bytearray(fixtures.build_channels([("FloatChannel", "X", [])]))
        struct.pack_into("<I", raw, 0, 0xDEADBEEF)
        with self.assertRaises(TakFormatError) as cm:
            ch.parse(bytes(raw))
        self.assertIn("magic", str(cm.exception))

    def test_truncated_sample_block_is_reported(self):
        raw = fixtures.build_channels([("Vector3fChannel", "Translation",
                                        [(i, (0.0, 0.0, 0.0)) for i in range(10)])])
        with self.assertRaises(TakFormatError):
            ch.parse(raw[:-40])

    def test_trailing_bytes_are_reported(self):
        raw = fixtures.build_channels([("FloatChannel", "X", [])]) + b"\x00" * 8
        with self.assertRaises(TakFormatError) as cm:
            ch.parse(raw)
        self.assertIn("trailing", str(cm.exception))


class TestNodes(unittest.TestCase):
    def test_parses_nodes_and_flattens_properties(self):
        raw = fixtures.build_nodes([
            ("TelemetryNode", {}),
            ("RigidBody", {"NodeName": "Example Body", "UserData": "4"}),
            ("Marker", {"NodeName": "Marker 001"}),
        ])
        version, nodes = nd.parse(raw)
        self.assertEqual(version, 3)
        self.assertEqual([n.type_name for n in nodes],
                         ["TelemetryNode", "RigidBody", "Marker"])
        self.assertEqual(nodes[1].name, "Example Body")
        self.assertEqual(nodes[1].properties["UserData"], "4")

    def test_node_count_mismatch_is_reported(self):
        raw = bytearray(fixtures.build_nodes([("Marker", {"NodeName": "M"})]))
        struct.pack_into("<I", raw, 1, 5)  # claim more nodes than exist
        with self.assertRaises(TakFormatError) as cm:
            nd.parse(bytes(raw))
        self.assertIn("declares 5", str(cm.exception))


class TestDocument(unittest.TestCase):
    def setUp(self):
        self.doc = TakDocument(fixtures.simple_take(frames=5, rigid_bodies=2, markers=3),
                               name="fixture")

    def test_binds_channels_to_assets(self):
        self.assertEqual(len(self.doc.rigid_bodies), 2)
        self.assertEqual(len(self.doc.markers), 3)
        self.assertEqual(len(self.doc.cameras), 1)
        self.assertEqual(len(self.doc.telemetry), 1)

    def test_rigid_body_gets_all_three_channels(self):
        rb = self.doc.rigid_bodies[0]
        self.assertEqual(rb.translation.name, "Translation")
        self.assertEqual(rb.rotation.name, "Rotation")
        self.assertEqual(rb.error.name, "MarkerError")
        self.assertEqual(rb.id, "10")

    def test_marker_has_position_only(self):
        m = self.doc.markers[0]
        self.assertIsNotNone(m.translation)
        self.assertIsNone(m.rotation)

    def test_frame_extent_and_rate(self):
        self.assertEqual(self.doc.frame_count, 5)
        self.assertEqual(self.doc.frame_range, (0, 4))
        self.assertEqual(self.doc.frame_rate, 120.0)

    def test_missing_required_stream_is_reported(self):
        data = fixtures.build_ole({"Nodes.dat": fixtures.build_nodes([("Marker", {})])})
        with self.assertRaises(TakFormatError) as cm:
            TakDocument(data)
        self.assertIn("Channels.dat", str(cm.exception))

    def test_unbindable_layout_is_reported(self):
        # A RigidBody whose channels are missing must fail loudly rather than
        # silently shifting every later asset onto the wrong data.
        data = fixtures.build_ole({
            "Channels.dat": fixtures.build_channels([("Vector3fChannel", "Translation", [])]),
            "Nodes.dat": fixtures.build_nodes([("RigidBody", {"NodeName": "X"})]),
        })
        with self.assertRaises(TakFormatError):
            TakDocument(data)


if __name__ == "__main__":
    unittest.main()
