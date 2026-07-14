import datetime
import importlib.util
import io
import json
import pathlib
import unittest
from contextlib import redirect_stdout


ROOT = pathlib.Path(__file__).resolve().parent
MODULE_PATH = ROOT / "box" / "d1_oledb_canary.py"


def load_canary():
    spec = importlib.util.spec_from_file_location("d1_oledb_canary_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeField:
    def __init__(self, value):
        self.Value = value


class FakeRecordset:
    def __init__(self, rows=None, open_error=None, queries=None):
        self.rows = list(rows or [])
        self.open_error = open_error
        self.queries = queries if queries is not None else []
        self.index = 0
        self.closed = False

    @property
    def EOF(self):
        return self.index >= len(self.rows)

    def Open(self, query, connection, cursor_type, lock_type):
        self.queries.append(query)
        if self.open_error:
            raise self.open_error
        return None

    def Fields(self, name):
        row = self.rows[self.index]
        if name not in row:
            raise KeyError(name)
        return FakeField(row[name])

    def MoveNext(self):
        self.index += 1

    def Close(self):
        self.closed = True


class FakeConnection:
    def __init__(self):
        self.CommandTimeout = None
        self.closed = False

    def Close(self):
        self.closed = True


class D1OleDbCanaryTests(unittest.TestCase):
    def setUp(self):
        self.canary = load_canary()

    def probe(self, recordsets, now=None, monotonic=None, connect_fn=None):
        queue = list(recordsets)
        connection = FakeConnection()
        calls = []

        def connect(catalog, dsn):
            calls.append((catalog, dsn))
            return connection

        result = self.canary.probe(
            connect_fn=connect_fn or connect,
            recordset_factory=lambda: queue.pop(0),
            now_utc=now or datetime.datetime(2026, 7, 14, 7, 30, 0),
            monotonic=monotonic or (lambda: 0.0),
        )
        return result, connection, calls

    def test_exact_allowlist_queries_confirmed_candidates_first(self):
        specs = self.canary.VALUE_SPECS

        self.assertEqual([spec["key"] for spec in specs], [
            "bus_F", "u2_GV", "u1_F", "u2_F", "u3_F",
        ])
        self.assertEqual(specs[0]["value_name"], r"22kV\22kV_db_Unit_st22kV_nF")
        self.assertEqual(specs[1]["value_name"], r"U2\LCU2_db_Unit_stGov_nGV")
        self.assertNotIn("realopening2", json.dumps(specs))
        self.assertNotIn("H2-GV", json.dumps(specs))

    def test_query_uses_quoted_value_name_absolute_window_and_last_timestep(self):
        queries = []
        empty = [FakeRecordset(queries=queries) for _ in range(5)]

        result, connection, calls = self.probe(empty)

        self.assertTrue(result["available"])
        self.assertEqual(connection.CommandTimeout, 3)
        self.assertEqual(calls, [(self.canary.CATALOG, self.canary.DSN)])
        self.assertEqual(queries[0], (
            "TAG:R,'22kV\\22kV_db_Unit_st22kV_nF',"
            "'2026-07-13 07:30:00.000','2026-07-14 07:30:00.000',"
            "'TIMESTEP=300,2'"
        ))

    def test_prefers_realvalue_and_falls_back_to_variantvalue(self):
        recordsets = [
            FakeRecordset([{
                "ValueID": 12,
                "Timestamp": "2026-07-14 07:29:00.000",
                "RealValue": 49.98,
                "VariantValue": 1.0,
                "Quality": 0xC0,
            }]),
            FakeRecordset([{
                "ValueID": 31,
                "Timestamp": "2026-07-14 07:28:00.000",
                "VariantValue": 82.25,
                "Quality": 0xC1,
            }]),
        ] + [FakeRecordset() for _ in range(3)]

        result, _, _ = self.probe(recordsets)

        self.assertEqual(result["results"]["bus_F"]["last"], 49.98)
        self.assertEqual(result["results"]["bus_F"]["value_field"], "RealValue")
        self.assertEqual(result["results"]["u2_GV"]["last"], 82.25)
        self.assertEqual(result["results"]["u2_GV"]["value_field"], "VariantValue")
        self.assertTrue(result["results"]["u2_GV"]["quality_good"])

    def test_latest_bad_quality_sample_wins_over_older_good_sample(self):
        recordsets = [FakeRecordset([
            {
                "ValueID": 12,
                "Timestamp": "2026-07-14 07:20:00.000",
                "RealValue": 50.0,
                "Quality": 0xC0,
            },
            {
                "ValueID": 12,
                "Timestamp": "2026-07-14 07:29:00.000",
                "RealValue": 49.9,
                "Quality": 0x40,
            },
        ])] + [FakeRecordset() for _ in range(4)]

        result, _, _ = self.probe(recordsets)
        bus = result["results"]["bus_F"]

        self.assertEqual(bus["last"], 49.9)
        self.assertEqual(bus["quality"], 0x40)
        self.assertFalse(bus["quality_good"])
        self.assertEqual(bus["status"], "bad_quality")
        self.assertFalse(bus["realtime"])

    def test_out_of_range_value_remains_diagnostic_only(self):
        recordsets = [FakeRecordset([{
            "ValueID": 12,
            "Timestamp": "2026-07-14 07:29:00.000",
            "RealValue": 500.0,
            "Quality": 0xC0,
        }])] + [FakeRecordset() for _ in range(4)]

        result, _, _ = self.probe(recordsets)
        bus = result["results"]["bus_F"]

        self.assertEqual(bus["last"], 500.0)
        self.assertFalse(bus["in_range"])
        self.assertEqual(bus["status"], "out_of_range")
        self.assertNotIn("tags", result)

    def test_nan_and_infinity_are_rejected_before_strict_json_output(self):
        recordsets = [
            FakeRecordset([{
                "ValueID": 12,
                "Timestamp": "2026-07-14 07:29:00.000",
                "RealValue": float("nan"),
                "Quality": 0xC0,
            }]),
            FakeRecordset([{
                "ValueID": 31,
                "Timestamp": "2026-07-14 07:29:00.000",
                "RealValue": float("inf"),
                "Quality": 0xC0,
            }]),
        ] + [FakeRecordset() for _ in range(3)]

        result, _, _ = self.probe(recordsets)

        self.assertEqual(result["results"]["bus_F"]["status"], "invalid_value")
        self.assertIsNone(result["results"]["bus_F"]["last"])
        self.assertEqual(result["results"]["u2_GV"]["status"], "invalid_value")
        self.assertIsNone(result["results"]["u2_GV"]["last"])
        json.dumps(result, allow_nan=False)

    def test_one_query_failure_does_not_abort_or_leak_connection_material(self):
        recordsets = [
            FakeRecordset(open_error=RuntimeError(
                "Provider=WinCCOLEDBProvider.1;Password={two words};Server=MAINPC")),
            FakeRecordset([{
                "ValueID": 31,
                "Timestamp": "2026-07-14 07:29:00.000",
                "RealValue": 82.0,
                "Quality": 0xC0,
            }]),
        ] + [FakeRecordset() for _ in range(3)]

        result, _, _ = self.probe(recordsets)
        encoded = json.dumps(result)

        self.assertEqual(result["results"]["bus_F"]["status"], "query_error")
        self.assertNotIn("two words", encoded)
        self.assertNotIn("MAINPC", encoded)
        self.assertEqual(result["results"]["u2_GV"]["status"], "ok")

    def test_connect_failure_is_additive_and_does_not_echo_exception(self):
        result, _, _ = self.probe(
            [],
            connect_fn=lambda *_args: (_ for _ in ()).throw(
                RuntimeError("Password={two words};Data Source=MAINPC\\WINCC")),
        )

        encoded = json.dumps(result)
        self.assertFalse(result["available"])
        self.assertEqual(result["attempted"], 0)
        self.assertNotIn("two words", encoded)
        self.assertNotIn("MAINPC", encoded)

    def test_total_budget_marks_remaining_candidates_without_querying_them(self):
        times = iter([0.0, 0.0, 11.0, 11.0])
        queries = []
        recordsets = [FakeRecordset(queries=queries) for _ in range(5)]

        result, _, _ = self.probe(recordsets, monotonic=lambda: next(times))

        self.assertEqual(len(queries), 1)
        self.assertEqual(result["results"]["u2_GV"]["status"], "budget_exhausted")
        self.assertEqual(result["results"]["u3_F"]["status"], "budget_exhausted")

    def test_main_prints_one_strict_json_document(self):
        payload = {"available": False, "results": {}}
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            self.canary.main(
                argv=["--station", "Dakrosa1", "--raw-canary"],
                probe_fn=lambda: payload,
            )

        self.assertEqual(json.loads(stdout.getvalue()), payload)
        self.assertNotIn("NaN", stdout.getvalue())

    def test_main_requires_exact_station_and_raw_canary_flags(self):
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            self.canary.main(
                argv=["--station", "Dakrosa2", "--raw-canary"],
                probe_fn=lambda: self.fail("unauthorized invocation must not query"),
            )

        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["available"])
        self.assertEqual(payload["status"], "not_authorized")


if __name__ == "__main__":
    unittest.main()
