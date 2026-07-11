import datetime
import io
import json
import os
import pathlib
import re
import sys
import types
import unittest
from collections import Counter
from contextlib import redirect_stdout
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
    def test_energy_5min_normalizes_only_dakrosa2_unit_power_from_kw(self):
        reader = load_reader_namespace({
            "WINCC_STATION_NAME": "Dakrosa2",
            "WINCC_READ_MODE": "raw",
        })
        out = {
            "station": "Dakrosa2",
            "tags": {
                "bus_P": {"avg": 2.41},
                "u1_P": {"avg": 791.5},
            },
        }

        reader["_set_energy_5min"](out)

        self.assertEqual(out["energy_5min"]["bus_MWh_5min"], 0.200833)
        self.assertEqual(out["energy_5min"]["u1_MWh_5min"], 0.065958)

    def test_energy_5min_keeps_dakrosa1_unit_power_in_mw(self):
        reader = load_reader_namespace({"WINCC_STATION_NAME": "Dakrosa1"})
        out = {
            "station": "Dakrosa1",
            "tags": {"u1_P": {"avg": 2.49}},
        }

        reader["_set_energy_5min"](out)

        self.assertEqual(out["energy_5min"]["u1_MWh_5min"], 0.2075)

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
        self.assertEqual(calls, [{
            "inventory_limit": 0,
            "candidate_limit": 128,
            "station_name": "Dakrosa1",
        }])

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

    def test_complete_runtime_snapshot_skips_slow_archive_scan(self):
        reader = load_reader_namespace({
            "WINCC_READ_MODE": "raw",
            "WINCC_STATION_NAME": "Dakrosa2",
        })
        out = {
            "snapshot_utc": "2026-07-10T06:40:00Z",
            "window_min": 5,
            "station": "Dakrosa2",
            "tags": {},
        }

        def attach_runtime(payload):
            stat = {
                "count": 1,
                "last": 791.5,
                "min": 791.5,
                "max": 791.5,
                "avg": 791.5,
                "last_ts": payload["snapshot_utc"],
                "source": "wincc-dmclient",
                "realtime": True,
            }
            for name in ("bus_P", "u1_P", "u2_P", "u3_P"):
                payload["tags"][name] = dict(stat)
            for index in range(101):
                payload["tags"][f"runtime_tag_{index}"] = dict(stat)
            payload["runtime_snapshot"] = {
                "available": True,
                "attempted": 93,
                "accepted": 91,
                "rejected": 2,
            }

        reader["_attach_runtime_snapshot"] = attach_runtime
        reader["_sql_master"] = lambda: self.fail(
            "complete native Runtime data must not open the archive database")

        stdout = io.StringIO()
        with redirect_stdout(stdout):
            reader["_main_raw"](out)

        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["read_mode"], "runtime")
        self.assertEqual(payload["tags"]["u1_P"]["last"], 791.5)
        self.assertTrue(payload["runtime_snapshot"]["available"])

    def test_optional_runtime_tags_do_not_disable_complete_core_snapshot(self):
        reader = load_reader_namespace({
            "WINCC_READ_MODE": "raw",
            "WINCC_STATION_NAME": "Dakrosa2",
        })
        stat = {"last": 1.0}
        tags = {"runtime_tag_%d" % index: stat for index in range(101)}
        tags.update({name: stat for name in ("bus_P", "u1_P", "u2_P", "u3_P")})
        out = {
            "tags": tags,
            "runtime_snapshot": {
                "available": True,
                "attempted": 116,
                "accepted": 91,
                "required_attempted": 93,
                "required_accepted": 91,
            },
        }

        self.assertTrue(reader["_runtime_snapshot_complete"](out))

    def test_partial_runtime_snapshot_keeps_archive_fallback(self):
        reader = load_reader_namespace({
            "WINCC_READ_MODE": "raw",
            "WINCC_STATION_NAME": "Dakrosa2",
        })
        out = {
            "snapshot_utc": "2026-07-10T06:40:00Z",
            "window_min": 5,
            "station": "Dakrosa2",
            "tags": {},
        }

        def attach_runtime(payload):
            payload["tags"]["u1_P"] = {
                "count": 1,
                "last": 791.5,
                "min": 791.5,
                "max": 791.5,
                "avg": 791.5,
                "last_ts": payload["snapshot_utc"],
                "source": "wincc-dmclient",
                "realtime": True,
            }
            payload["runtime_snapshot"] = {
                "available": True,
                "attempted": 93,
                "accepted": 40,
                "rejected": 53,
            }

        class Connection:
            def Close(self):
                pass

        reader["_attach_runtime_snapshot"] = attach_runtime
        reader["_sql_master"] = lambda: (Connection(), r".\WINCC")
        reader["_find_live_archive"] = lambda _conn: (
            "CC_Dakrosa2_TLG_F", datetime.datetime(2026, 7, 10, 6, 40))
        reader["MAP"] = {1: "u1_P", 2: "archive_only"}
        reader["_read_raw_tag"] = lambda _conn, _db, vid, _live: {
            "count": 10,
            "last": float(vid),
            "min": float(vid),
            "max": float(vid),
            "avg": float(vid),
            "last_ts": "2026-07-10T06:39:59Z",
            "source": "archive",
        }

        stdout = io.StringIO()
        with redirect_stdout(stdout):
            reader["_main_raw"](out)

        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["read_mode"], "raw")
        self.assertEqual(payload["archive"], "CC_Dakrosa2_TLG_F")
        self.assertEqual(payload["tags"]["u1_P"]["source"], "wincc-dmclient")
        self.assertEqual(payload["tags"]["archive_only"]["source"], "archive")

    def test_runtime_metadata_cannot_fast_path_with_too_few_actual_tags(self):
        reader = load_reader_namespace({
            "WINCC_READ_MODE": "raw",
            "WINCC_STATION_NAME": "Dakrosa2",
        })
        out = {
            "snapshot_utc": "2026-07-10T06:40:00Z",
            "window_min": 5,
            "station": "Dakrosa2",
            "tags": {},
        }

        def attach_runtime(payload):
            stat = {
                "count": 1,
                "last": 50.0,
                "min": 50.0,
                "max": 50.0,
                "avg": 50.0,
                "last_ts": payload["snapshot_utc"],
                "source": "wincc-dmclient",
                "realtime": True,
            }
            for index in range(20):
                payload["tags"][f"runtime_tag_{index}"] = dict(stat)
            payload["runtime_snapshot"] = {
                "available": True,
                "attempted": 93,
                "accepted": 91,
                "rejected": 2,
            }

        class Connection:
            def Close(self):
                pass

        reader["_attach_runtime_snapshot"] = attach_runtime
        reader["_sql_master"] = lambda: (Connection(), r".\WINCC")
        reader["_find_live_archive"] = lambda _conn: (
            "CC_Dakrosa2_TLG_F", datetime.datetime(2026, 7, 10, 6, 40))
        reader["MAP"] = {1: "archive_only"}
        reader["_read_raw_tag"] = lambda *_args: {
            "count": 10,
            "last": 1.0,
            "min": 1.0,
            "max": 1.0,
            "avg": 1.0,
            "last_ts": "2026-07-10T06:39:59Z",
            "source": "archive",
        }

        stdout = io.StringIO()
        with redirect_stdout(stdout):
            reader["_main_raw"](out)

        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["read_mode"], "raw")
        self.assertIn("archive_only", payload["tags"])

    def test_consistent_short_runtime_inventory_cannot_fast_path(self):
        reader = load_reader_namespace({
            "WINCC_READ_MODE": "raw",
            "WINCC_STATION_NAME": "Dakrosa2",
        })
        out = {
            "snapshot_utc": "2026-07-10T06:40:00Z",
            "window_min": 5,
            "station": "Dakrosa2",
            "tags": {},
        }

        def attach_runtime(payload):
            stat = {
                "count": 1,
                "last": 10.0,
                "min": 10.0,
                "max": 10.0,
                "avg": 10.0,
                "last_ts": payload["snapshot_utc"],
                "source": "wincc-dmclient",
                "realtime": True,
            }
            for name in ("bus_P", "u1_P", "u2_P", "u3_P"):
                payload["tags"][name] = dict(stat)
            payload["runtime_snapshot"] = {
                "available": True,
                "attempted": 4,
                "accepted": 4,
                "rejected": 0,
            }

        class Connection:
            def Close(self):
                pass

        reader["_attach_runtime_snapshot"] = attach_runtime
        reader["_sql_master"] = lambda: (Connection(), r".\WINCC")
        reader["_find_live_archive"] = lambda _conn: (
            "CC_Dakrosa2_TLG_F", datetime.datetime(2026, 7, 10, 6, 40))
        reader["MAP"] = {1: "archive_only"}
        reader["_read_raw_tag"] = lambda *_args: {
            "count": 10,
            "last": 1.0,
            "min": 1.0,
            "max": 1.0,
            "avg": 1.0,
            "last_ts": "2026-07-10T06:39:59Z",
            "source": "archive",
        }

        stdout = io.StringIO()
        with redirect_stdout(stdout):
            reader["_main_raw"](out)

        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["read_mode"], "raw")
        self.assertIn("archive_only", payload["tags"])

    def test_archive_discovery_failure_preserves_partial_runtime_values(self):
        reader = load_reader_namespace({
            "WINCC_READ_MODE": "raw",
            "WINCC_STATION_NAME": "Dakrosa2",
        })
        out = {
            "snapshot_utc": "2026-07-10T06:40:00Z",
            "window_min": 5,
            "station": "Dakrosa2",
            "tags": {},
        }

        def attach_runtime(payload):
            payload["tags"]["u1_P"] = {
                "count": 1,
                "last": 791.5,
                "min": 791.5,
                "max": 791.5,
                "avg": 791.5,
                "last_ts": payload["snapshot_utc"],
                "source": "wincc-dmclient",
                "realtime": True,
            }
            payload["runtime_snapshot"] = {
                "available": True,
                "attempted": 93,
                "accepted": 1,
                "rejected": 92,
            }

        class Connection:
            def Close(self):
                pass

        reader["_attach_runtime_snapshot"] = attach_runtime
        reader["_sql_master"] = lambda: (Connection(), r".\WINCC")
        reader["_find_live_archive"] = lambda _conn: (_ for _ in ()).throw(
            RuntimeError("archive enumeration failed"))

        stdout = io.StringIO()
        with redirect_stdout(stdout):
            reader["_main_raw"](out)

        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["tags"]["u1_P"]["last"], 791.5)
        self.assertIn("archive enumeration failed", payload["error"])
        self.assertEqual(payload["energy_5min"]["u1_MWh_5min"], 0.065958)


if __name__ == "__main__":
    unittest.main()
