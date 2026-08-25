"""Tests for unit/rotation handling and CSV emission."""

import csv
import io
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fixtures  # noqa: E402

from motivebatch import csvwriter, units  # noqa: E402
from motivebatch.tak import TakDocument  # noqa: E402


class TestUnits(unittest.TestCase):
    def test_scale_from_meters(self):
        self.assertEqual(units.scale_from_meters(units.Meters), 1.0)
        self.assertEqual(units.scale_from_meters(units.Centimeters), 100.0)
        self.assertEqual(units.scale_from_meters(units.Millimeters), 1000.0)

    def test_unknown_unit_rejected(self):
        with self.assertRaises(ValueError):
            units.scale_from_meters("furlongs")

    def test_identity_quaternion_is_zero_rotation(self):
        for order in units.EULER_ORDERS:
            got = units.quaternion_to_euler(0.0, 0.0, 0.0, 1.0, order)
            for v in got:
                self.assertAlmostEqual(v, 0.0, places=9)

    def test_principal_axis_rotations(self):
        h = math.sqrt(0.5)
        cases = {"X": (h, 0.0, 0.0, h), "Y": (0.0, h, 0.0, h), "Z": (0.0, 0.0, h, h)}
        for axis, q in cases.items():
            got = units.quaternion_to_euler(q[0], q[1], q[2], q[3], "XYZ")
            idx = "XYZ".index(axis)
            self.assertAlmostEqual(got[idx], 90.0, places=4,
                                   msg="90 deg about {} misread as {}".format(axis, got))
            for other in range(3):
                if other != idx:
                    self.assertAlmostEqual(got[other], 0.0, places=4)

    def test_all_six_orders_accepted(self):
        self.assertEqual(len(units.EULER_ORDERS), 6)
        for order in units.EULER_ORDERS:
            units.quaternion_to_euler(0.5, 0.5, 0.5, 0.5, order)

    def test_unknown_order_rejected(self):
        with self.assertRaises(ValueError):
            units.quaternion_to_euler(0.0, 0.0, 0.0, 1.0, "ABC")

    def test_non_unit_quaternion_is_normalised(self):
        a = units.quaternion_to_euler(0.0, 0.0, 0.0, 1.0, "XYZ")
        b = units.quaternion_to_euler(0.0, 0.0, 0.0, 5.0, "XYZ")
        for x, y in zip(a, b):
            self.assertAlmostEqual(x, y, places=9)


def _render(doc, **kw):
    buf = io.StringIO()
    csvwriter.write(doc, buf, **kw)
    return list(csv.reader(io.StringIO(buf.getvalue())))


class TestCsvWriter(unittest.TestCase):
    def setUp(self):
        self.doc = TakDocument(
            fixtures.simple_take(frames=4, rigid_bodies=2, markers=3), name="fixture")

    def test_column_count_without_markers(self):
        rows = _render(self.doc)
        # 2 index columns + 2 bodies x (4 rot + 3 pos + 1 error)
        self.assertEqual(len(rows[7]), 2 + 2 * 8)

    def test_column_count_with_markers(self):
        rows = _render(self.doc, markers=True)
        self.assertEqual(len(rows[7]), 2 + 2 * 8 + 3 * 3)

    def test_euler_rotation_narrows_columns(self):
        rows = _render(self.doc, rotation="XYZ")
        self.assertEqual(len(rows[7]), 2 + 2 * 7)

    def test_header_rows_describe_columns(self):
        rows = _render(self.doc, markers=True)
        self.assertEqual(rows[0][0], "Format Version")
        self.assertIn("Take Name", rows[0])
        self.assertEqual(rows[3][2], "Rigid Body")
        self.assertEqual(rows[4][2], "Body 0")
        self.assertEqual(rows[5][2], "10")
        self.assertEqual(rows[6][2], "Rotation")
        self.assertEqual(rows[7][:2], ["Frame", "Time (Seconds)"])
        self.assertEqual(rows[3][-1], "Marker")

    def test_no_header_emits_data_only(self):
        rows = _render(self.doc, header=False)
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0][0], "0")

    def test_frame_and_time_columns(self):
        rows = _render(self.doc)[8:]
        self.assertEqual([r[0] for r in rows], ["0", "1", "2", "3"])
        self.assertAlmostEqual(float(rows[2][1]), 2.0 / 120.0, places=6)

    def test_units_scale_positions(self):
        meters = _render(self.doc)[8]
        millis = _render(self.doc, units=units.Millimeters)[8]
        # First body's position X is 0.0; use the second body, which is at 1.0.
        m_val = float(meters[8 + 4])
        mm_val = float(millis[8 + 4])
        self.assertAlmostEqual(mm_val, m_val * 1000.0, places=3)

    def test_missing_samples_render_empty(self):
        # A body whose rotation channel has no samples leaves blanks, not zeros.
        data = fixtures.build_ole({
            "Channels.dat": fixtures.build_channels([
                ("Vector3fChannel", "Translation", [(0, (1.0, 2.0, 3.0))]),
                ("QuaternionChannel", "Rotation", []),
                ("FloatChannel", "MarkerError", []),
            ]),
            "Nodes.dat": fixtures.build_nodes([("RigidBody", {"NodeName": "B"})]),
        })
        rows = _render(TakDocument(data, name="t"))
        self.assertEqual(rows[8][2:6], ["", "", "", ""])   # rotation blank
        self.assertEqual(rows[8][6], "1.000000")            # position present

    def test_rejects_unknown_rotation(self):
        with self.assertRaises(ValueError):
            _render(self.doc, rotation="nope")


if __name__ == "__main__":
    unittest.main()
