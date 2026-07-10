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


if __name__ == "__main__":
    unittest.main()
