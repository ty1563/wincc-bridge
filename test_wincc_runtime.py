import unittest

from box.wincc_runtime import build_probe, select_candidate_tags


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


if __name__ == "__main__":
    unittest.main()
