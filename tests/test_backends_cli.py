"""Tests for backend selection, DLL discovery and the CLI."""

import io
import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fixtures  # noqa: E402

from motivebatch import backends, cli, config  # noqa: E402
from motivebatch.backends import base as fmt  # noqa: E402
from motivebatch.backends.nmotive import (NMotiveBackend, _verify_assembly,  # noqa: E402
                                          find_motive_root,
                                          prepare_native_environment)
from motivebatch.errors import BackendUnavailable, ExportNotSupported  # noqa: E402


class _Tmp(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="motivebatch-test-")
        self.tak = os.path.join(self.dir, "Sample Take.tak")
        with open(self.tak, "wb") as fh:
            fh.write(fixtures.simple_take(frames=3, rigid_bodies=2, markers=2))


class TestBackendSelection(_Tmp):
    def test_native_is_chosen_when_nmotive_is_unusable(self):
        backend, notes = backends.build(backends.AUTO, dll_path=None, fmt=fmt.CSV,
                                        allow_prompt=False, use_config=False)
        if sys.platform.startswith("win"):
            self.skipTest("NMotive may legitimately be available on Windows")
        self.assertEqual(backend.name, backends.NATIVE)
        self.assertTrue(notes, "a skipped backend should explain itself")

    def test_native_refuses_formats_it_cannot_produce(self):
        with self.assertRaises(ExportNotSupported):
            backends.build(backends.NATIVE, fmt=fmt.AVI, allow_prompt=False,
                           use_config=False)

    def test_explicit_nmotive_raises_rather_than_falling_back(self):
        if sys.platform.startswith("win"):
            self.skipTest("NMotive may legitimately be available on Windows")
        with self.assertRaises(BackendUnavailable):
            backends.build(backends.NMOTIVE, fmt=fmt.CSV, allow_prompt=False,
                           use_config=False)

    def test_available_lists_both_backends(self):
        names = [n for n, _, _ in backends.available()]
        self.assertEqual(sorted(names), [backends.NATIVE, backends.NMOTIVE])


class TestNMotiveGuards(_Tmp):
    def test_off_windows_reason_names_the_platform(self):
        if sys.platform.startswith("win"):
            self.skipTest("Windows can load NMotive")
        with self.assertRaises(BackendUnavailable) as cm:
            NMotiveBackend("/nonexistent/NMotive.dll")._load()
        self.assertIn("mixed-mode", cm.exception.reason)

    def test_truncated_dll_is_diagnosed(self):
        # Exactly the failure mode of a partially-copied NMotive.dll: the PE
        # section table describes more bytes than the file holds.
        path = os.path.join(self.dir, "NMotive.dll")
        head = bytearray(0x400)
        head[0:2] = b"MZ"
        struct.pack_into("<I", head, 0x3C, 0x80)
        head[0x80:0x84] = b"PE\x00\x00"
        struct.pack_into("<H", head, 0x86, 1)      # one section
        struct.pack_into("<H", head, 0x94, 0xF0)   # optional header size
        sec = 0x80 + 24 + 0xF0
        struct.pack_into("<II", head, sec + 16, 10_000_000, 0x400)  # size, ptr
        with open(path, "wb") as fh:
            fh.write(head)
        with self.assertRaises(BackendUnavailable) as cm:
            _verify_assembly(path, "nmotive")
        self.assertIn("truncated", cm.exception.reason)

    def test_non_dll_is_rejected(self):
        path = os.path.join(self.dir, "NMotive.dll")
        with open(path, "wb") as fh:
            fh.write(b"this is not a PE file")
        with self.assertRaises(BackendUnavailable) as cm:
            _verify_assembly(path, "nmotive")
        self.assertIn("not a Windows DLL", cm.exception.reason)


class TestMotiveRootDiscovery(_Tmp):
    """Qt needs the Motive install root, which sits above NMotive.dll."""

    def _install(self, with_platforms=True, with_exe=False):
        root = os.path.join(self.dir, "Motive")
        x64 = os.path.join(root, "assemblies", "x64")
        os.makedirs(x64)
        if with_platforms:
            os.makedirs(os.path.join(root, "platforms"))
            open(os.path.join(root, "platforms", "qwindows.dll"), "wb").close()
        if with_exe:
            open(os.path.join(root, "Motive.exe"), "wb").close()
        dll = os.path.join(x64, "NMotive.dll")
        open(dll, "wb").close()
        return root, dll

    def test_walks_up_to_the_platforms_folder(self):
        root, dll = self._install()
        self.assertEqual(find_motive_root(dll), root)

    def test_motive_exe_also_identifies_the_root(self):
        root, dll = self._install(with_platforms=False, with_exe=True)
        self.assertEqual(find_motive_root(dll), root)

    def test_returns_none_for_an_orphaned_dll(self):
        dll = os.path.join(self.dir, "NMotive.dll")
        open(dll, "wb").close()
        self.assertIsNone(find_motive_root(dll))

    def test_environment_points_qt_at_the_plugins(self):
        root, dll = self._install()
        saved = {k: os.environ.get(k) for k in
                 ("QT_QPA_PLATFORM_PLUGIN_PATH", "QT_PLUGIN_PATH", "PATH")}
        try:
            got = prepare_native_environment(dll, "nmotive")
            self.assertEqual(got, root)
            self.assertEqual(os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"],
                             os.path.join(root, "platforms"))
            self.assertIn(root, os.environ["PATH"])
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_orphaned_dll_is_explained_not_crashed(self):
        # Qt aborts the process if it starts without plugins, so this has to
        # fail up front with an actionable message instead.
        dll = os.path.join(self.dir, "NMotive.dll")
        open(dll, "wb").close()
        with self.assertRaises(BackendUnavailable) as cm:
            prepare_native_environment(dll, "nmotive")
        self.assertIn("Motive install directory", cm.exception.reason)

    def test_missing_platforms_folder_is_explained(self):
        root, dll = self._install(with_platforms=False, with_exe=True)
        with self.assertRaises(BackendUnavailable) as cm:
            prepare_native_environment(dll, "nmotive")
        self.assertIn("platforms", cm.exception.reason)


class TestExportFallback(_Tmp):
    """A take NMotive cannot open should still convert via the portable reader."""

    class _FailingNMotive:
        name = backends.NMOTIVE

        def __init__(self, message):
            self.message = message
            self.called = False

        def export(self, source, dest, fmt=fmt.CSV, **options):
            self.called = True
            # Leave a partial file behind, as a failed exporter would.
            with open(dest, "w") as fh:
                fh.write("partial")
            raise RuntimeError(self.message)

    def test_falls_back_when_nmotive_cannot_read_the_take(self):
        stub = self._FailingNMotive("File was written by a newer software version "
                                    "and cannot be read.")
        dest = os.path.join(self.dir, "out.csv")
        notes = []
        backends.export_with_fallback(stub, self.tak, dest, fmt=fmt.CSV,
                                      preference=backends.AUTO, log=notes.append,
                                      allow_fallback=True)
        self.assertTrue(stub.called)
        self.assertTrue(os.path.isfile(dest))
        with open(dest) as fh:
            self.assertIn("Format Version", fh.readline())
        self.assertTrue(any("newer version of Motive" in n for n in notes))

    def test_partial_output_is_replaced_not_appended(self):
        stub = self._FailingNMotive("boom")
        dest = os.path.join(self.dir, "out.csv")
        backends.export_with_fallback(stub, self.tak, dest, fmt=fmt.CSV,
                                      preference=backends.AUTO, allow_fallback=True)
        with open(dest) as fh:
            self.assertNotIn("partial", fh.read(200))

    def test_no_fallback_when_a_backend_was_demanded(self):
        stub = self._FailingNMotive("boom")
        with self.assertRaises(RuntimeError):
            backends.export_with_fallback(stub, self.tak,
                                          os.path.join(self.dir, "out.csv"),
                                          fmt=fmt.CSV, preference=backends.NMOTIVE)

    def test_no_fallback_for_formats_the_reader_cannot_produce(self):
        stub = self._FailingNMotive("boom")
        with self.assertRaises(RuntimeError):
            backends.export_with_fallback(stub, self.tak,
                                          os.path.join(self.dir, "out.avi"),
                                          fmt=fmt.AVI, preference=backends.AUTO)

    def test_windows_does_not_substitute_the_reader_by_default(self):
        # A Motive machine must produce Motive's output or say why it cannot;
        # a silent drop to best-effort fidelity would be worse than failing.
        stub = self._FailingNMotive("File was written by a newer software version "
                                    "and cannot be read.")
        notes = []
        with self.assertRaises(RuntimeError):
            backends.export_with_fallback(
                stub, self.tak, os.path.join(self.dir, "out.csv"), fmt=fmt.CSV,
                preference=backends.AUTO, log=notes.append, allow_fallback=False)
        self.assertTrue(any("--allow-fallback" in n for n in notes),
                        "refusing to fall back must say how to opt in")

    def test_partial_output_is_discarded_when_failing_loudly(self):
        stub = self._FailingNMotive("boom")
        dest = os.path.join(self.dir, "out.csv")
        with self.assertRaises(RuntimeError):
            backends.export_with_fallback(stub, self.tak, dest, fmt=fmt.CSV,
                                          preference=backends.AUTO,
                                          allow_fallback=False)
        self.assertFalse(os.path.exists(dest))

    def test_fallback_default_is_off_on_windows_only(self):
        expected = not sys.platform.startswith("win")
        self.assertEqual(backends.fallback_default(), expected)

    def test_cli_no_fallback_flag_surfaces_the_failure(self):
        import motivebatch.backends as b
        real = b.build
        stub = self._FailingNMotive("File was written by a newer software version "
                                    "and cannot be read.")
        b.build = lambda *a, **k: (stub, [])
        try:
            rc = cli.main([self.tak, "--output-dir", self.dir, "--quiet",
                           "--no-fallback"])
        finally:
            b.build = real
        self.assertEqual(rc, 1)
        # No half-written CSV may be left behind to look like a success.
        self.assertFalse(os.path.isfile(os.path.join(self.dir, "Sample Take.csv")))

    def test_version_mismatch_is_explained_in_plain_words(self):
        msg = backends.explain_failure(
            RuntimeError("File was written by a newer software version and cannot be read."))
        self.assertIn("newer version of Motive", msg)

    def test_cli_reports_foreign_errors_without_a_traceback(self):
        # A .NET exception escaping the backend must not crash the batch.
        import motivebatch.backends as b
        real = b.build
        stub = self._FailingNMotive("File was written by a newer software version "
                                    "and cannot be read.")
        b.build = lambda *a, **k: (stub, [])
        try:
            rc = cli.main([self.tak, "--output-dir", self.dir, "--quiet",
                           "--allow-fallback"])
        finally:
            b.build = real
        self.assertEqual(rc, 0)          # fell back successfully
        self.assertTrue(os.path.isfile(os.path.join(self.dir, "Sample Take.csv")))


class TestNMotiveExporterToggles(_Tmp):
    """The CSVExporter property mapping, verified without the real assembly."""

    class _Exporter:
        def __init__(self):
            self.WriteHeader = None
            self.WriteMarkers = None
            self.WriteRigidBodies = None
            self.WriteRigidBodyMarkers = None
            self.WriteBones = None
            self.WriteBoneMarkers = None
            self.WriteQualityStats = None
            self.RotationType = None
            self.Units = None
            self.exported = None

        def Export(self, take, dest, overwrite):
            self.exported = (take, dest, overwrite)

    def _stub_nm(self, exporter):
        class Rotation:
            QuaternionFormat = "quat"
            XYZ = "XYZ"

        class LengthUnits:
            Units_Meters = "m"
            Units_Centimeters = "cm"
            Units_Millimeters = "mm"

        class NM:
            pass

        nm = NM()
        nm.Rotation = Rotation
        nm.LengthUnits = LengthUnits
        nm.Take = lambda path: ("take", path)
        nm.CSVExporter = lambda: exporter
        return nm

    def _run(self, **options):
        exporter = self._Exporter()
        backend = NMotiveBackend("/fake/NMotive.dll")
        backend._load = lambda: self._stub_nm(exporter)
        backend.export(self.tak, os.path.join(self.dir, "out.csv"), **options)
        return exporter

    def test_defaults_match_motives_export_dialog(self):
        e = self._run()
        for prop in ("WriteHeader", "WriteMarkers", "WriteRigidBodies",
                     "WriteRigidBodyMarkers", "WriteBones", "WriteBoneMarkers",
                     "WriteQualityStats"):
            self.assertIs(getattr(e, prop), True,
                          "{} must default on, as Motive does".format(prop))

    def test_no_markers_also_drops_dependent_marker_sets(self):
        e = self._run(markers=False)
        self.assertIs(e.WriteMarkers, False)
        self.assertIs(e.WriteRigidBodyMarkers, False)
        self.assertIs(e.WriteBoneMarkers, False)
        self.assertIs(e.WriteRigidBodies, True)   # bodies still exported

    def test_dependent_sets_can_be_overridden_independently(self):
        e = self._run(markers=False, rigid_body_markers=True)
        self.assertIs(e.WriteMarkers, False)
        self.assertIs(e.WriteRigidBodyMarkers, True)

    def test_units_and_rotation_are_translated(self):
        e = self._run(units="Millimeters", rotation="XYZ")
        self.assertEqual(e.Units, "mm")
        self.assertEqual(e.RotationType, "XYZ")

    def test_missing_properties_are_skipped_not_fatal(self):
        # Older NMotive builds lack some toggles; setting them must not raise.
        exporter = self._Exporter()
        del exporter.WriteBoneMarkers
        backend = NMotiveBackend("/fake/NMotive.dll")
        backend._load = lambda: self._stub_nm(exporter)
        backend.export(self.tak, os.path.join(self.dir, "out.csv"))
        self.assertIs(exporter.WriteMarkers, True)

    def test_nmotive_set_reaches_the_exporter(self):
        e = self._run(nmotive_set={"WriteQualityStats": False})
        self.assertIs(e.WriteQualityStats, False)

    def test_unknown_nmotive_set_property_is_reported(self):
        with self.assertRaises(ExportNotSupported) as cm:
            self._run(nmotive_set={"NoSuchProperty": True})
        self.assertIn("dump-exporter", str(cm.exception))


class TestConfigDiscovery(_Tmp):
    def test_explicit_path_wins(self):
        dll = os.path.join(self.dir, "NMotive.dll")
        open(dll, "wb").close()
        self.assertEqual(config.find_dll(dll), dll)

    def test_directory_is_accepted(self):
        dll = os.path.join(self.dir, "NMotive.dll")
        open(dll, "wb").close()
        self.assertEqual(config.find_dll(self.dir), dll)

    def test_env_var_is_consulted(self):
        dll = os.path.join(self.dir, "NMotive.dll")
        open(dll, "wb").close()
        old = os.environ.get(config.ENV_VAR)
        os.environ[config.ENV_VAR] = dll
        try:
            self.assertEqual(config.find_dll(None, use_config=False,
                                             search_install=False), dll)
        finally:
            if old is None:
                del os.environ[config.ENV_VAR]
            else:
                os.environ[config.ENV_VAR] = old

    def test_missing_path_yields_none(self):
        self.assertIsNone(config.find_dll(os.path.join(self.dir, "absent.dll"),
                                          use_config=False, search_install=False))

    def test_prompt_skipped_when_not_a_tty(self):
        self.assertIsNone(config.prompt_for_dll(io.StringIO(""), io.StringIO()))


class TestCliHelpers(_Tmp):
    def test_classify_splits_dll_from_takes(self):
        inputs, dll = cli._classify(["a.tak", "NMotive.dll", "b.tak"])
        self.assertEqual(inputs, ["a.tak", "b.tak"])
        self.assertEqual(dll, "NMotive.dll")

    def test_classify_without_dll(self):
        inputs, dll = cli._classify(["a.tak"])
        self.assertEqual(inputs, ["a.tak"])
        self.assertIsNone(dll)

    def test_unique_path_avoids_overwriting(self):
        p = os.path.join(self.dir, "out.csv")
        self.assertEqual(cli.unique_path(p), p)
        open(p, "w").close()
        self.assertEqual(cli.unique_path(p), os.path.join(self.dir, "out (1).csv"))
        open(os.path.join(self.dir, "out (1).csv"), "w").close()
        self.assertEqual(cli.unique_path(p), os.path.join(self.dir, "out (2).csv"))


class TestCliEndToEnd(_Tmp):
    def test_converts_into_output_dir(self):
        rc = cli.main([self.tak, "--output-dir", self.dir, "--quiet"])
        self.assertEqual(rc, 0)
        out = os.path.join(self.dir, "Sample Take.csv")
        self.assertTrue(os.path.isfile(out))
        with open(out) as fh:
            self.assertIn("Format Version", fh.readline())

    def test_beside_input_names_file_after_take(self):
        rc = cli.main([self.tak, "--beside-input", "--quiet"])
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.isfile(os.path.join(self.dir, "Sample Take.csv")))

    def test_second_run_does_not_overwrite(self):
        cli.main([self.tak, "--output-dir", self.dir, "--quiet"])
        cli.main([self.tak, "--output-dir", self.dir, "--quiet"])
        self.assertTrue(os.path.isfile(os.path.join(self.dir, "Sample Take (1).csv")))

    def test_overwrite_flag_reuses_the_name(self):
        cli.main([self.tak, "--output-dir", self.dir, "--quiet"])
        cli.main([self.tak, "--output-dir", self.dir, "--quiet", "--overwrite"])
        self.assertFalse(os.path.isfile(os.path.join(self.dir, "Sample Take (1).csv")))

    def test_dll_argument_is_accepted_positionally(self):
        dll = os.path.join(self.dir, "NMotive.dll")
        open(dll, "wb").close()
        rc = cli.main([dll, self.tak, "--output-dir", self.dir, "--quiet",
                       "--no-prompt"])
        self.assertEqual(rc, 0)

    def test_missing_input_reports_failure(self):
        rc = cli.main([os.path.join(self.dir, "absent.tak"), "--quiet",
                       "--output-dir", self.dir])
        self.assertEqual(rc, 1)

    def test_no_arguments_is_a_usage_error(self):
        self.assertEqual(cli.main(["--quiet"]), 2)

    def test_output_with_multiple_inputs_rejected(self):
        self.assertEqual(cli.main([self.tak, self.tak, "-o", "x.csv"]), 2)

    def test_markers_are_included_by_default(self):
        # Motive's own export includes markers, so ours must too; --no-markers
        # is the opt-out. Before 0.3.0 this defaulted the other way.
        cli.main([self.tak, "--output-dir", self.dir, "--quiet", "--overwrite"])
        default = open(os.path.join(self.dir, "Sample Take.csv")).read()
        cli.main([self.tak, "--output-dir", self.dir, "--quiet", "--overwrite",
                  "--no-markers"])
        narrow = open(os.path.join(self.dir, "Sample Take.csv")).read()
        self.assertGreater(len(default), len(narrow))
        self.assertIn("Marker", default.splitlines()[3])
        self.assertNotIn("Marker", narrow.splitlines()[3])

    def test_desktop_dir_is_a_directory_or_none(self):
        d = cli.desktop_dir()
        self.assertTrue(d is None or os.path.isdir(d))


if __name__ == "__main__":
    unittest.main()
