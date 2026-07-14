import json
import subprocess
import unittest
from types import SimpleNamespace
from unittest import mock

from bridge import collect


class CollectRuntimeProbeTests(unittest.TestCase):
    def test_local_raw_collection_enables_isolated_runtime_probe_by_default(self):
        cfg = {"winccbox": {"mode": "local"}}

        self.assertEqual(collect._runtime_probe_args(cfg), ["--probe-runtime"])

    def test_remote_raw_collection_uses_metadata_only_probe_by_default(self):
        cfg = {"winccbox": {"mode": "remote"}}

        self.assertEqual(collect._runtime_probe_args(cfg), ["--probe-runtime-metadata"])

    def test_station_config_can_request_full_remote_value_probe(self):
        cfg = {
            "winccbox": {"mode": "remote"},
            "station": {"runtime_probe": True},
        }

        self.assertEqual(collect._runtime_probe_args(cfg), ["--probe-runtime"])

    def test_station_config_can_disable_runtime_probe_without_disabling_rawdump(self):
        cfg = {"station": {"runtime_probe": False}}

        self.assertEqual(collect._runtime_probe_args(cfg), [])

    def test_string_false_is_treated_as_disabled_for_legacy_toml_parser(self):
        cfg = {"station": {"runtime_probe": "false"}}

        self.assertEqual(collect._runtime_probe_args(cfg), [])


class D1OleDbCanaryCollectionTests(unittest.TestCase):
    def cfg(self, station="Dakrosa1", enabled=True):
        return {
            "station": {"name": station, "d1_oledb_value_probe": enabled},
            "winccbox": {
                "mode": "remote",
                "python32": "C:/Python37-32/python.exe",
                "reader": "C:/Users/dell/win32deploy/oledb_reader.py",
                "target": "dell@169.254.1.2",
            },
        }

    @staticmethod
    def result(payload, returncode=0, stderr=""):
        return SimpleNamespace(
            returncode=returncode,
            stdout=json.dumps(payload),
            stderr=stderr,
        )

    def test_dakrosa1_attaches_second_process_result_after_rawdump_parses(self):
        raw = {"station": "Dakrosa1", "raw_dump": True, "blocks": ["kept"]}
        probe = {"available": True, "backend": "wincc-oledb-valuename", "results": {}}

        with mock.patch.object(collect, "_ssh_base", return_value=["ssh", "target"]), \
                mock.patch.object(
                    collect.subprocess,
                    "run",
                    side_effect=[self.result(raw), self.result(probe)],
                ) as run:
            result = collect.collect_rawdump(self.cfg())

        self.assertEqual(result["blocks"], ["kept"])
        self.assertEqual(result["oledb_value_probe"], probe)
        helper_cmd = run.call_args_list[1].args[0]
        self.assertIn("C:/Users/dell/win32deploy/d1_oledb_canary.py", helper_cmd)
        self.assertEqual(helper_cmd[-4:], [
            "C:/Users/dell/win32deploy/d1_oledb_canary.py",
            "--station",
            "Dakrosa1",
            "--raw-canary",
        ])
        self.assertEqual(run.call_args_list[1].kwargs["timeout"], 15)

    def test_canary_timeout_keeps_already_parsed_rawdump(self):
        raw = {"station": "Dakrosa1", "raw_dump": True, "blocks": ["kept"]}

        with mock.patch.object(collect, "_ssh_base", return_value=["ssh", "target"]), \
                mock.patch.object(
                    collect.subprocess,
                    "run",
                    side_effect=[
                        self.result(raw),
                        subprocess.TimeoutExpired(["python", "canary"], 15),
                    ],
                ):
            result = collect.collect_rawdump(self.cfg())

        self.assertEqual(result["blocks"], ["kept"])
        self.assertEqual(result["oledb_value_probe"]["status"], "timeout")
        self.assertFalse(result["oledb_value_probe"]["available"])

    def test_nonstandard_canary_json_is_rejected_without_losing_rawdump(self):
        raw = {"station": "Dakrosa1", "raw_dump": True, "blocks": ["kept"]}
        invalid = SimpleNamespace(
            returncode=0,
            stdout='{"available":true,"last":NaN}',
            stderr="",
        )

        with mock.patch.object(collect, "_ssh_base", return_value=["ssh", "target"]), \
                mock.patch.object(
                    collect.subprocess,
                    "run",
                    side_effect=[self.result(raw), invalid],
                ):
            result = collect.collect_rawdump(self.cfg())

        self.assertEqual(result["blocks"], ["kept"])
        self.assertEqual(result["oledb_value_probe"]["status"], "invalid_output")

    def test_invalid_rawdump_never_launches_canary(self):
        invalid_raw = SimpleNamespace(returncode=0, stdout="not-json", stderr="")

        with mock.patch.object(collect, "_ssh_base", return_value=["ssh", "target"]), \
                mock.patch.object(
                    collect.subprocess,
                    "run",
                    return_value=invalid_raw,
                ) as run:
            with self.assertRaises(json.JSONDecodeError):
                collect.collect_rawdump(self.cfg())

        self.assertEqual(run.call_count, 1)

    def test_dakrosa2_never_launches_dakrosa1_canary(self):
        raw = {"station": "Dakrosa2", "raw_dump": True, "blocks": []}

        with mock.patch.object(collect, "_ssh_base", return_value=["ssh", "target"]), \
                mock.patch.object(
                    collect.subprocess,
                    "run",
                    return_value=self.result(raw),
                ) as run:
            result = collect.collect_rawdump(self.cfg())

        self.assertNotIn("oledb_value_probe", result)
        self.assertEqual(run.call_count, 1)

    def test_explicit_false_kill_switch_skips_canary(self):
        raw = {"station": "Dakrosa1", "raw_dump": True, "blocks": []}

        with mock.patch.object(collect, "_ssh_base", return_value=["ssh", "target"]), \
                mock.patch.object(
                    collect.subprocess,
                    "run",
                    return_value=self.result(raw),
                ) as run:
            result = collect.collect_rawdump(self.cfg(enabled="false"))

        self.assertNotIn("oledb_value_probe", result)
        self.assertEqual(run.call_count, 1)

    def test_existing_probe_field_is_never_overwritten_or_relaunched(self):
        existing = {"available": True, "status": "reader-owned"}
        raw = {
            "station": "Dakrosa1",
            "raw_dump": True,
            "blocks": [],
            "oledb_value_probe": existing,
        }

        with mock.patch.object(collect, "_ssh_base", return_value=["ssh", "target"]), \
                mock.patch.object(
                    collect.subprocess,
                    "run",
                    return_value=self.result(raw),
                ) as run:
            result = collect.collect_rawdump(self.cfg())

        self.assertEqual(result["oledb_value_probe"], existing)
        self.assertEqual(run.call_count, 1)

    def test_missing_config_and_payload_station_fails_closed(self):
        raw = {"raw_dump": True, "blocks": []}
        cfg = self.cfg()
        cfg["station"].pop("name")

        with mock.patch.object(collect, "_ssh_base", return_value=["ssh", "target"]), \
                mock.patch.object(
                    collect.subprocess,
                    "run",
                    return_value=self.result(raw),
                ) as run:
            result = collect.collect_rawdump(cfg)

        self.assertNotIn("oledb_value_probe", result)
        self.assertEqual(run.call_count, 1)

    def test_legacy_config_uses_exact_parsed_payload_station(self):
        raw = {"station": "Dakrosa1", "raw_dump": True, "blocks": []}
        probe = {"available": False, "backend": "wincc-oledb-valuename"}
        cfg = self.cfg()
        cfg.pop("station")

        with mock.patch.object(collect, "_ssh_base", return_value=["ssh", "target"]), \
                mock.patch.object(
                    collect.subprocess,
                    "run",
                    side_effect=[self.result(raw), self.result(probe)],
                ) as run:
            result = collect.collect_rawdump(cfg)

        self.assertEqual(result["oledb_value_probe"], probe)
        self.assertEqual(run.call_count, 2)

    def test_conflicting_config_and_payload_station_fails_closed(self):
        raw = {"station": "Dakrosa1", "raw_dump": True, "blocks": []}

        with mock.patch.object(collect, "_ssh_base", return_value=["ssh", "target"]), \
                mock.patch.object(
                    collect.subprocess,
                    "run",
                    return_value=self.result(raw),
                ) as run:
            result = collect.collect_rawdump(self.cfg(station="Dakrosa2"))

        self.assertNotIn("oledb_value_probe", result)
        self.assertEqual(run.call_count, 1)

    def test_absent_kill_switch_defaults_on_for_exact_dakrosa1(self):
        raw = {"station": "Dakrosa1", "raw_dump": True, "blocks": []}
        probe = {"available": False, "backend": "wincc-oledb-valuename"}
        cfg = self.cfg()
        cfg["station"].pop("d1_oledb_value_probe")

        with mock.patch.object(collect, "_ssh_base", return_value=["ssh", "target"]), \
                mock.patch.object(
                    collect.subprocess,
                    "run",
                    side_effect=[self.result(raw), self.result(probe)],
                ) as run:
            result = collect.collect_rawdump(cfg)

        self.assertEqual(result["oledb_value_probe"], probe)
        self.assertEqual(run.call_count, 2)

    def test_nonzero_canary_exit_is_diagnostic_and_keeps_rawdump(self):
        raw = {"station": "Dakrosa1", "raw_dump": True, "blocks": ["kept"]}

        with mock.patch.object(collect, "_ssh_base", return_value=["ssh", "target"]), \
                mock.patch.object(
                    collect.subprocess,
                    "run",
                    side_effect=[self.result(raw), self.result({}, returncode=7)],
                ):
            result = collect.collect_rawdump(self.cfg())

        self.assertEqual(result["blocks"], ["kept"])
        self.assertEqual(result["oledb_value_probe"]["status"], "process_error")
        self.assertEqual(result["oledb_value_probe"]["returncode"], 7)

    def test_local_dakrosa1_runs_helper_with_station_environment(self):
        raw = {"station": "Dakrosa1", "raw_dump": True, "blocks": []}
        probe = {"available": True, "backend": "wincc-oledb-valuename"}
        cfg = self.cfg()
        cfg["winccbox"]["mode"] = "local"

        with mock.patch.object(
                collect.subprocess,
                "run",
                side_effect=[self.result(raw), self.result(probe)],
        ) as run:
            result = collect.collect_rawdump(cfg)

        self.assertEqual(result["oledb_value_probe"], probe)
        self.assertEqual(run.call_args_list[1].args[0][-4:], [
            "C:/Users/dell/win32deploy/d1_oledb_canary.py",
            "--station",
            "Dakrosa1",
            "--raw-canary",
        ])
        self.assertEqual(
            run.call_args_list[1].kwargs["env"]["WINCC_STATION_NAME"],
            "Dakrosa1",
        )


if __name__ == "__main__":
    unittest.main()
