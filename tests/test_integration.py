"""End-to-end checks against a real Motive take.

Skipped unless a .tak is present in temp/ (which is gitignored), so a bare
clone still runs a green suite.
"""

import csv
import glob
import io
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from motivebatch import Take, csvwriter, units  # noqa: E402
from motivebatch.tak import load  # noqa: E402

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SAMPLES = sorted(glob.glob(os.path.join(_REPO, "temp", "*.tak")))


@unittest.skipUnless(_SAMPLES, "no .tak sample in temp/")
class TestRealTake(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = _SAMPLES[0]
        cls.doc = load(cls.path)

    def test_streams_are_recognised(self):
        for name in ("Channels.dat", "Nodes.dat"):
            self.assertIn(name, self.doc.ole.stream_names)

    def test_every_channel_is_bound_to_an_asset(self):
        bound = len(self.doc.telemetry)
        for a in self.doc.rigid_bodies:
            bound += 3
        for a in self.doc.cameras:
            bound += 2
        bound += len(self.doc.markers)
        self.assertEqual(bound, len(self.doc.channels),
                         "channel binding must account for every channel")

    def test_take_has_solved_assets(self):
        self.assertTrue(self.doc.rigid_bodies or self.doc.markers)
        self.assertGreater(self.doc.frame_count, 0)

    def test_frame_rate_recovered_from_cameras(self):
        self.assertTrue(self.doc.frame_rate is None or self.doc.frame_rate > 0)

    def test_quaternions_are_unit_norm(self):
        for rb in self.doc.rigid_bodies:
            if not rb.has_rotation:
                continue
            for _frame, q in rb.rotation.samples()[:200]:
                norm = sum(v * v for v in q) ** 0.5
                self.assertAlmostEqual(norm, 1.0, places=3)

    def test_csv_shape_matches_asset_count(self):
        buf = io.StringIO()
        csvwriter.write(self.doc, buf, markers=True)
        rows = list(csv.reader(io.StringIO(buf.getvalue())))
        expected = 2 + 8 * len(self.doc.rigid_bodies) + 3 * len(self.doc.markers)
        self.assertEqual(len(rows[7]), expected)
        self.assertEqual(len(rows) - 8, self.doc.frame_count)

    def test_public_api_round_trip(self):
        import tempfile
        take = Take(self.path)
        self.assertEqual(take.frame_count, self.doc.frame_count)
        with tempfile.TemporaryDirectory() as d:
            out = take.to_csv(os.path.join(d, "out.csv"), units=units.Millimeters)
            self.assertTrue(os.path.isfile(out))
            self.assertGreater(os.path.getsize(out), 1000)


if __name__ == "__main__":
    unittest.main()
