import ctypes
import math
import os
import tempfile
import unittest
from unittest import mock

from box.wincc_runtime import (
    DMVarKeyW,
    WinCCRuntimeAPI,
    build_probe,
    locate_wincc_bin,
    probe_runtime,
    select_candidate_tags,
)


class FakeRuntimeAPI:
    def __init__(self):
        self.read_names = []

    def runtime_project(self):
        return r"C:\SCADA\Dakrosa1\Dakrosa1.mcp"

    def enumerate_tags(self, project):
        self.project_seen = project
        return [
            {"id": 1, "name": r"U1\LCU1_db_Unit_stAlt_nP"},
            {"id": 2, "name": r"U1\LCU1_db_Unit_stAlt_nQ"},
            {"id": 3, "name": r"U1\LCU1_db_AI_stSpd_nEng"},
            {"id": 4, "name": r"U1\InternalCounter"},
            {"id": 5, "name": r"U1\BearingTemp_1"},
        ]

    def tag_type(self, project, tag):
        return {"code": 8, "name": "Float", "size": 4}

    def read_numeric(self, name, type_code):
        self.read_names.append(name)
        values = {
            r"U1\LCU1_db_Unit_stAlt_nP": 1500.25,
            r"U1\LCU1_db_Unit_stAlt_nQ": 75.5,
            r"U1\LCU1_db_AI_stSpd_nEng": 500.0,
            r"U1\BearingTemp_1": 52.75,
        }
        return {"value": values[name], "state": 0, "quality": 192}


class WinCCRuntimeProbeTests(unittest.TestCase):
    def test_candidate_filter_keeps_electrical_mechanical_and_temperature_tags(self):
        tags = FakeRuntimeAPI().enumerate_tags("unused")

        selected = select_candidate_tags(tags, limit=20)

        self.assertEqual(
            {tag["name"] for tag in selected},
            {
                r"U1\LCU1_db_Unit_stAlt_nP",
                r"U1\LCU1_db_Unit_stAlt_nQ",
                r"U1\LCU1_db_AI_stSpd_nEng",
                r"U1\BearingTemp_1",
            },
        )

    def test_probe_returns_inventory_and_quality_aware_candidate_values(self):
        api = FakeRuntimeAPI()

        result = build_probe(api, inventory_limit=100, candidate_limit=20)

        self.assertTrue(result["available"])
        self.assertEqual(result["backend"], "wincc-apicf")
        self.assertEqual(result["project"], "Dakrosa1.mcp")
        self.assertEqual(result["total_tags"], 5)
        self.assertFalse(result["inventory_truncated"])
        self.assertEqual(len(result["inventory"]), 5)
        self.assertEqual(len(result["candidates"]), 4)
        self.assertEqual(result["candidates"][0]["type_code"], 8)
        self.assertEqual(result["candidates"][0]["quality"], 192)
        self.assertEqual(set(api.read_names), {
            r"U1\LCU1_db_Unit_stAlt_nP",
            r"U1\LCU1_db_Unit_stAlt_nQ",
            r"U1\LCU1_db_AI_stSpd_nEng",
            r"U1\BearingTemp_1",
        })

    def test_probe_degrades_to_diagnostic_payload_instead_of_raising(self):
        class BrokenAPI:
            def runtime_project(self):
                raise RuntimeError("ODK license unavailable")

        result = build_probe(BrokenAPI())

        self.assertFalse(result["available"])
        self.assertIn("ODK license unavailable", result["error"])

    def test_ctypes_adapter_reads_float_with_state_and_quality(self):
        class ReadFloat:
            def __call__(self, name, state_ptr, quality_ptr):
                self.name = name
                state_ptr._obj.value = 7
                quality_ptr._obj.value = 192
                return 49.98

        read_float = ReadFloat()
        fake_apicf = type("FakeAPICF", (), {
            "GetTagFloatStateQCWait": read_float,
        })()
        api = WinCCRuntimeAPI(dmclient=object(), apicf=fake_apicf, configure=False)

        result = api.read_numeric(r"22kV\Bus_nF", 8)

        self.assertEqual(read_float.name, b"22kV\\Bus_nF")
        self.assertAlmostEqual(result["value"], 49.98, places=3)
        self.assertEqual(result["state"], 7)
        self.assertEqual(result["quality"], 192)

    def test_ctypes_adapter_rejects_non_numeric_types(self):
        api = WinCCRuntimeAPI(dmclient=object(), apicf=object(), configure=False)

        with self.assertRaisesRegex(ValueError, "unsupported numeric type"):
            api.read_numeric("TextTag", 10)

    def test_ctypes_adapter_discovers_runtime_project_and_enumerates_tags(self):
        class RuntimeProject:
            def __call__(self, buffer, size, error):
                buffer.value = r"C:\SCADA\Dakrosa1\Dakrosa1.mcp"
                return 1

        class EnumVariables:
            def __call__(self, project, tag_filter, callback, user, error):
                self.project = project
                for tag_id, name in ((11, r"U1\Power_nP"), (12, r"U1\Speed_nEng")):
                    key = DMVarKeyW()
                    key.dwKeyType = 3
                    key.dwID = tag_id
                    key.szName = name
                    callback(ctypes.pointer(key), None)
                return 1

        enum_variables = EnumVariables()
        fake_dm = type("FakeDM", (), {
            "DMGetRuntimeProjectW": RuntimeProject(),
            "DMEnumVariablesW": enum_variables,
        })()
        api = WinCCRuntimeAPI(dmclient=fake_dm, apicf=object(), configure=False)

        project = api.runtime_project()
        tags = api.enumerate_tags(project)

        self.assertEqual(project, r"C:\SCADA\Dakrosa1\Dakrosa1.mcp")
        self.assertEqual(enum_variables.project, project)
        self.assertEqual(tags, [
            {"id": 11, "name": r"U1\Power_nP"},
            {"id": 12, "name": r"U1\Speed_nEng"},
        ])

    def test_ctypes_adapter_reads_configured_tag_type(self):
        class GetVarType:
            def __call__(self, project, key_ptr, count, type_ptr, error):
                self.key_name = key_ptr._obj.szName
                self.count = count
                type_ptr._obj.dwType = 9
                type_ptr._obj.dwSize = 8
                type_ptr._obj.szTypeName = "Double"
                return 1

        get_var_type = GetVarType()
        fake_dm = type("FakeDM", (), {"DMGetVarTypeW": get_var_type})()
        api = WinCCRuntimeAPI(dmclient=fake_dm, apicf=object(), configure=False)

        result = api.tag_type(
            r"C:\SCADA\Dakrosa1\Dakrosa1.mcp",
            {"id": 11, "name": r"U1\Power_nP"},
        )

        self.assertEqual(get_var_type.key_name, r"U1\Power_nP")
        self.assertEqual(get_var_type.count, 1)
        self.assertEqual(result, {"code": 9, "size": 8, "name": "Double"})

    def test_wincc_bin_discovery_honors_explicit_environment_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            open(os.path.join(temp_dir, "apicf.dll"), "wb").close()
            open(os.path.join(temp_dir, "dmclient.dll"), "wb").close()

            with mock.patch.dict(os.environ, {"WINCC_BIN": temp_dir}, clear=False):
                result = locate_wincc_bin()

        self.assertEqual(result, temp_dir)

    def test_auto_loading_rejects_non_32_bit_python_before_touching_wincc(self):
        if ctypes.sizeof(ctypes.c_void_p) == 4:
            self.skipTest("test only applies to the development 64-bit interpreter")

        with self.assertRaisesRegex(RuntimeError, "32-bit Python"):
            WinCCRuntimeAPI()

    def test_public_probe_accepts_factory_for_safe_boundary_testing(self):
        api = FakeRuntimeAPI()
        api.connect = mock.Mock()
        api.disconnect = mock.Mock()

        result = probe_runtime(api_factory=lambda: api, candidate_limit=2)

        self.assertTrue(result["available"])
        self.assertEqual(len(result["candidates"]), 2)
        api.connect.assert_called_once_with()
        api.disconnect.assert_called_once_with()

    def test_ctypes_adapter_rejects_non_finite_values_before_json(self):
        class ReadFloat:
            def __call__(self, name, state_ptr, quality_ptr):
                return math.nan

        fake_apicf = type("FakeAPICF", (), {
            "GetTagFloatStateQCWait": ReadFloat(),
        })()
        api = WinCCRuntimeAPI(dmclient=object(), apicf=fake_apicf, configure=False)

        with self.assertRaisesRegex(ValueError, "non-finite"):
            api.read_numeric("BadFloat", 8)

    def test_ctypes_adapter_connects_and_disconnects_data_manager(self):
        class Connect:
            def __call__(self, app_name, callback, user, error):
                self.app_name = app_name
                self.callback = callback
                return 1

        class Disconnect:
            def __call__(self, error):
                self.called = True
                return 1

        connect = Connect()
        disconnect = Disconnect()
        fake_dm = type("FakeDM", (), {
            "DMConnectW": connect,
            "DMDisConnectW": disconnect,
        })()
        api = WinCCRuntimeAPI(dmclient=fake_dm, apicf=object(), configure=False)

        api.connect()
        api.disconnect()

        self.assertEqual(connect.app_name, "wincc-bridge")
        self.assertIsNotNone(connect.callback)
        self.assertTrue(disconnect.called)


if __name__ == "__main__":
    unittest.main()
