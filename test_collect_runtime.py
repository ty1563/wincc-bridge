import unittest

from bridge.collect import _runtime_probe_args


class CollectRuntimeProbeTests(unittest.TestCase):
    def test_local_raw_collection_enables_isolated_runtime_probe_by_default(self):
        cfg = {"winccbox": {"mode": "local"}}

        self.assertEqual(_runtime_probe_args(cfg), ["--probe-runtime"])

    def test_remote_raw_collection_disables_runtime_probe_by_default(self):
        cfg = {"winccbox": {"mode": "remote"}}

        self.assertEqual(_runtime_probe_args(cfg), [])

    def test_station_config_can_disable_runtime_probe_without_disabling_rawdump(self):
        cfg = {"station": {"runtime_probe": False}}

        self.assertEqual(_runtime_probe_args(cfg), [])

    def test_string_false_is_treated_as_disabled_for_legacy_toml_parser(self):
        cfg = {"station": {"runtime_probe": "false"}}

        self.assertEqual(_runtime_probe_args(cfg), [])


if __name__ == "__main__":
    unittest.main()
