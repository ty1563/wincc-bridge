import datetime
import os
import pathlib
import re
import sys
import types
import unittest
from collections import Counter
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parent


def load_reader_namespace(env=None):
    """Load reader helpers without requiring pywin32 or running main()."""
    source = (ROOT / "box" / "oledb_reader.py").read_text(encoding="utf-8")
    source = source.rsplit("\nmain()", 1)[0]
    win32com = types.ModuleType("win32com")
    client = types.ModuleType("win32com.client")
    win32com.client = client
    with mock.patch.dict(sys.modules, {"win32com": win32com, "win32com.client": client}):
        with mock.patch.dict(os.environ, env or {}, clear=True):
            namespace = {"__name__": "oledb_reader_test"}
            exec(compile(source, "box/oledb_reader.py", "exec"), namespace)
    return namespace


class FakeField:
    def __init__(self, value):
        self.Value = value


class FakeRecordset:
    def __init__(self, rows):
        self.rows = rows
        self.index = 0

    @property
    def EOF(self):
        return self.index >= len(self.rows)

    def Fields(self, index):
        return FakeField(self.rows[self.index][index])

    def MoveNext(self):
        self.index += 1

    def Close(self):
        pass


class FakeConnection:
    def __init__(self, rows):
        self.rows = rows

    def Execute(self, sql):
        if "COUNT(DISTINCT" in sql:
            raise RuntimeError("count query is irrelevant to this behavior")
        rows = self.rows
        match = re.search(r"rn\s*(?:=|<=)\s*(\d+)", sql)
        if match:
            limit = int(match.group(1))
            counts = Counter()
            limited = []
            for row in rows:
                if counts[row[0]] >= limit:
                    continue
                counts[row[0]] += 1
                limited.append(row)
            rows = limited
        return FakeRecordset(rows)


class RawDumpMultiBlockTests(unittest.TestCase):
    def test_runtime_snapshot_defaults_on_only_for_raw_station_mode(self):
        self.assertTrue(load_reader_namespace(
            {"WINCC_READ_MODE": "raw"})["RUNTIME_SNAPSHOT"])
        self.assertFalse(load_reader_namespace()["RUNTIME_SNAPSHOT"])
        self.assertFalse(load_reader_namespace({
            "WINCC_READ_MODE": "raw",
            "WINCC_RUNTIME_SNAPSHOT": "false",
        })["RUNTIME_SNAPSHOT"])

    def test_raw_mode_exports_recent_fallback_blocks_for_each_value_id(self):
        reader = load_reader_namespace({"WINCC_READ_MODE": "raw"})
        rows = [
            [1, "tb1", "te4", 20, b"a" * 20],
            [2, "tb2", "te3", 20, b"b" * 20],
            [1, "tb3", "te2", 20, b"c" * 20],
            [2, "tb4", "te1", 20, b"d" * 20],
        ]

        blocks, _, total, truncated = reader["_dump_blocks"](
            FakeConnection(rows),
            "archive",
            datetime.datetime(2026, 7, 10),
            hours=2,
            cap=1024,
        )

        self.assertEqual(Counter(block["vid"] for block in blocks), Counter({1: 2, 2: 2}))
        self.assertEqual(total, 80)
        self.assertFalse(truncated)

    def test_provider_mode_keeps_one_block_per_value_id(self):
        reader = load_reader_namespace()
        rows = [
            [1, "tb1", "te4", 20, b"a" * 20],
            [2, "tb2", "te3", 20, b"b" * 20],
            [1, "tb3", "te2", 20, b"c" * 20],
            [2, "tb4", "te1", 20, b"d" * 20],
        ]

        blocks, _, total, truncated = reader["_dump_blocks"](
            FakeConnection(rows),
            "archive",
            datetime.datetime(2026, 7, 10),
            hours=2,
            cap=1024,
        )

        self.assertEqual(Counter(block["vid"] for block in blocks), Counter({1: 1, 2: 1}))
        self.assertEqual(total, 40)
        self.assertFalse(truncated)

    def test_runtime_probe_is_bounded_and_attached_to_raw_diagnostics(self):
        reader = load_reader_namespace()
        calls = []
        out = {}

        def probe(**kwargs):
            calls.append(kwargs)
            return {"available": True, "total_tags": 1754}

        reader["_attach_runtime_probe"](out, probe=probe)

        self.assertEqual(out["runtime_probe"]["total_tags"], 1754)
        self.assertEqual(calls, [{"inventory_limit": 0, "candidate_limit": 128}])

    def test_runtime_probe_failure_never_breaks_raw_archive_payload(self):
        reader = load_reader_namespace()
        out = {"archive": "CC_Dakrosa1_TLG_F"}

        def broken_probe(**_kwargs):
            raise RuntimeError("APICF load failed")

        reader["_attach_runtime_probe"](out, probe=broken_probe)

        self.assertEqual(out["archive"], "CC_Dakrosa1_TLG_F")
        self.assertFalse(out["runtime_probe"]["available"])
        self.assertIn("APICF load failed", out["runtime_probe"]["error"])

    def test_curated_runtime_snapshot_overrides_only_valid_archive_tags(self):
        reader = load_reader_namespace({"WINCC_READ_MODE": "raw"})
        out = {
            "snapshot_utc": "2026-07-10T04:10:00Z",
            "tags": {
                "u1_F": {"last": 2.01, "source": "archive"},
                "u1_P": {"last": 790.0, "source": "archive"},
            },
        }

        reader["_attach_runtime_snapshot"](
            out,
            snapshot=lambda station, snapshot_utc: {
                "available": True,
                "backend": "wincc-dmclient",
                "attempted": 75,
                "accepted": 1,
                "rejected": 74,
                "tags": {
                    "u1_F": {
                        "count": 1,
                        "last": 50.25,
                        "min": 50.25,
                        "max": 50.25,
                        "avg": 50.25,
                        "last_ts": snapshot_utc,
                        "source": "wincc-dmclient",
                        "realtime": True,
                    }
                },
            },
        )

        self.assertEqual(out["tags"]["u1_F"]["last"], 50.25)
        self.assertEqual(out["tags"]["u1_P"]["last"], 790.0)
        self.assertEqual(out["runtime_snapshot"]["accepted"], 1)
        self.assertNotIn("tags", out["runtime_snapshot"])


if __name__ == "__main__":
    unittest.main()
