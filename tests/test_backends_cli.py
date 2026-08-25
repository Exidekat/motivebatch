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
from motivebatch.backends.nmotive import NMotiveBackend, _verify_assembly  # noqa: E402
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

    def test_markers_widen_the_export(self):
        cli.main([self.tak, "--output-dir", self.dir, "--quiet", "--overwrite"])
        plain = open(os.path.join(self.dir, "Sample Take.csv")).read()
        cli.main([self.tak, "--output-dir", self.dir, "--quiet", "--overwrite",
                  "--markers"])
        wide = open(os.path.join(self.dir, "Sample Take.csv")).read()
        self.assertGreater(len(wide), len(plain))

    def test_desktop_dir_is_a_directory_or_none(self):
        d = cli.desktop_dir()
        self.assertTrue(d is None or os.path.isdir(d))


if __name__ == "__main__":
    unittest.main()
