import os
import hashlib
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from bridge import updater


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.payload


class StationReaderSyncTests(unittest.TestCase):
    def _repo(self, root):
        box = os.path.join(root, "box")
        os.makedirs(box)
        with open(os.path.join(box, "oledb_reader.py"), "wb") as f:
            f.write(b"current-reader")
        with open(os.path.join(box, "wincc_runtime.py"), "wb") as f:
            f.write(b"current-runtime")

    def _cfg(self, station):
        return {
            "station": {"name": station},
            "winccbox": {
                "mode": "remote",
                "user": "dell",
                "target": "dell@169.254.1.2",
                "reader": "C:/Users/dell/win32deploy/oledb_reader.py",
            },
        }

    def test_dakrosa1_syncs_pinned_legacy_reader_but_keeps_current_helpers(self):
        with tempfile.TemporaryDirectory() as root:
            self._repo(root)
            uploads = {}
            legacy = b"legacy-station1-reader"

            def fake_run(cmd, **kwargs):
                with open(cmd[-2], "rb") as f:
                    uploads[cmd[-1]] = f.read()
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            with mock.patch.object(updater, "REPO_ROOT", root), \
                    mock.patch.object(
                        updater,
                        "_urlopen",
                        return_value=FakeResponse(legacy),
                    ) as opened, \
                    mock.patch.object(
                        updater,
                        "DAKROSA1_LEGACY_READER_SHA256",
                        hashlib.sha256(legacy).hexdigest(),
                    ), \
                    mock.patch.object(updater.subprocess, "run", side_effect=fake_run):
                updater._sync_box(self._cfg("Dakrosa1"))

        reader_target = "dell@169.254.1.2:win32deploy/oledb_reader.py"
        runtime_target = "dell@169.254.1.2:win32deploy/wincc_runtime.py"
        self.assertEqual(uploads[reader_target], legacy)
        self.assertEqual(uploads[runtime_target], b"current-runtime")
        opened.assert_called_once_with(updater.DAKROSA1_LEGACY_READER_URL, timeout=30)

    def test_dakrosa2_syncs_current_reader_without_fetching_legacy_file(self):
        with tempfile.TemporaryDirectory() as root:
            self._repo(root)
            uploads = {}

            def fake_run(cmd, **kwargs):
                with open(cmd[-2], "rb") as f:
                    uploads[cmd[-1]] = f.read()
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            with mock.patch.object(updater, "REPO_ROOT", root), \
                    mock.patch.object(updater, "_urlopen") as opened, \
                    mock.patch.object(updater.subprocess, "run", side_effect=fake_run):
                updater._sync_box(self._cfg("Dakrosa2"))

        reader_target = "dell@169.254.1.2:win32deploy/oledb_reader.py"
        self.assertEqual(uploads[reader_target], b"current-reader")
        opened.assert_not_called()

    def test_startup_self_heal_syncs_only_dakrosa1(self):
        with mock.patch.object(updater, "_sync_box") as sync:
            changed = updater.sync_pinned_station_files(self._cfg("Dakrosa1"))

            self.assertTrue(changed)
            sync.assert_called_once()

        with mock.patch.object(updater, "_sync_box") as sync:
            changed = updater.sync_pinned_station_files(self._cfg("Dakrosa2"))

            self.assertFalse(changed)
            sync.assert_not_called()


if __name__ == "__main__":
    unittest.main()
