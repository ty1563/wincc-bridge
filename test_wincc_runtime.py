import ctypes
import contextlib
import io
import math
import os
import tempfile
import threading
import unittest
from unittest import mock

from box.wincc_runtime import (
    DMVarUpdateExW,
    DMVarKeyW,
    WinCCRuntimeAPI,
    build_probe,
    locate_wincc_bin,
    probe_runtime,
    read_curated_snapshot,
    run_callback_canary,
    select_candidate_tags,
)
from box import wincc_runtime


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
    def test_callback_canary_cli_requires_parent_watch_and_exact_modes(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit):
                wincc_runtime._main([
                    "--callback-canary",
                    "--station", "Dakrosa2",
                    "--mode", "local",
                    "--read-mode", "raw",
                ])

        self.assertIn("--watch-stdin", stderr.getvalue())

    def test_callback_canary_reports_values_and_cleans_up(self):
        events = []
        stop_event = threading.Event()

        class Subscription:
            taid = 44
            stats = {"callbacks": 1, "items": 2, "errors": 0, "oversized": 0}

        class API:
            def connect(self):
                self.connected = True

            def start_updates(self, names, callback, cycle):
                self.names = tuple(names)
                self.cycle = cycle
                callback({
                    "LV-KW": {
                        "value": 2.41, "state": 0, "quality": 192,
                        "variant_type": 4,
                    },
                    "H1-KW": {
                        "value": 791.5, "state": 0, "quality": 192,
                        "variant_type": 4,
                    },
                })
                return Subscription()

            def stop_updates(self, subscription):
                self.stopped = subscription.taid

            def disconnect(self):
                self.disconnected = True

        api = API()

        def emit(event):
            events.append(event)
            if event.get("event") == "heartbeat":
                stop_event.set()

        run_callback_canary(
            emit,
            stop_event,
            api_factory=lambda: api,
            heartbeat_sec=0.01,
            callback_timeout_sec=1.0,
            poll_sec=0.01,
        )

        event_names = [event["event"] for event in events]
        self.assertEqual(api.names, ("LV-KW", "H1-KW", "H2-KW", "H3-KW"))
        self.assertEqual(api.cycle, 2)
        self.assertIn("first_callback", event_names)
        self.assertIn("heartbeat", event_names)
        self.assertEqual(events[event_names.index("heartbeat")]["tags"]["LV-KW"]["quality"], 192)
        self.assertEqual(api.stopped, 44)
        self.assertTrue(api.disconnected)

    def test_callback_canary_pumps_owner_thread_messages_before_timeout(self):
        events = []
        stop_event = threading.Event()

        class Subscription:
            taid = 55
            stats = {"callbacks": 1, "items": 1, "errors": 0, "oversized": 0}

        class API:
            def connect(self):
                pass

            def start_updates(self, names, callback, cycle):
                self.callback = callback
                return Subscription()

            def stop_updates(self, subscription):
                pass

            def disconnect(self):
                pass

        api = API()
        pumped = []

        def pump_messages():
            if not pumped:
                pumped.append(True)
                api.callback({
                    "LV-KW": {
                        "value": 2.41, "state": 0, "quality": 192,
                        "variant_type": 4,
                    },
                })

        def emit(event):
            events.append(event)
            if event.get("event") == "heartbeat" and event.get("callbacks"):
                stop_event.set()

        run_callback_canary(
            emit,
            stop_event,
            api_factory=lambda: api,
            message_pump=pump_messages,
            heartbeat_sec=0.01,
            callback_timeout_sec=0.2,
            poll_sec=0.01,
        )

        self.assertTrue(pumped)
        self.assertIn("first_callback", [event["event"] for event in events])

    def test_callback_structures_match_packed_win32_header_layout(self):
        self.assertEqual(ctypes.sizeof(DMVarKeyW), 270)
        self.assertEqual(ctypes.sizeof(DMVarUpdateExW), 560)
        self.assertEqual(DMVarUpdateExW.dmTypeRef.offset, 0)
        self.assertEqual(DMVarUpdateExW.dmVarKey.offset, 266)
        self.assertEqual(DMVarUpdateExW.dmValue.offset, 536)
        self.assertEqual(DMVarUpdateExW.dwState.offset, 552)
        self.assertEqual(DMVarUpdateExW.dwQualityCode.offset, 556)

    def test_ctypes_adapter_runs_callback_subscription_lifecycle(self):
        order = []
        batches = []

        class Begin:
            def __call__(self, taid_ptr, error):
                order.append("begin")
                taid_ptr._obj.value = 73
                return 1

        class Start:
            def __call__(self, taid, keys, items, cycle, callback, user, error):
                order.append("start")
                self.taid = taid
                self.names = [keys[index].szName for index in range(items)]
                self.cycle = cycle
                updates = (DMVarUpdateExW * 2)()
                for index, (name, value) in enumerate((("LV-KW", 2.41), ("H1-KW", 791.5))):
                    updates[index].dmVarKey.szName = name
                    updates[index].dmValue.vt = 4
                    updates[index].dmValue.fltVal = value
                    updates[index].dwState = 0
                    updates[index].dwQualityCode = 192
                self.callback_result = callback(taid, updates, 2, user)
                return 1

        class End:
            def __call__(self, taid, error):
                order.append("end")
                return 1

        class Stop:
            def __call__(self, taid, error):
                order.append("stop")
                self.taid = taid
                return 1

        start = Start()
        stop = Stop()
        fake_dm = type("FakeDM", (), {
            "DMBeginStartVarUpdateW": Begin(),
            "DMStartVarUpdateExW": start,
            "DMEndStartVarUpdateW": End(),
            "DMStopVarUpdateW": stop,
        })()
        api = WinCCRuntimeAPI(dmclient=fake_dm, configure=False)

        subscription = api.start_updates(
            ["LV-KW", "H1-KW"], batches.append, cycle=2)

        self.assertEqual(order, ["begin", "start", "end"])
        self.assertEqual(start.taid, 73)
        self.assertEqual(start.names, ["LV-KW", "H1-KW"])
        self.assertEqual(start.cycle, 2)
        self.assertEqual(start.callback_result, 1)
        self.assertAlmostEqual(batches[0]["LV-KW"]["value"], 2.41, places=5)
        self.assertEqual(batches[0]["H1-KW"]["quality"], 192)

        api.stop_updates(subscription)

        self.assertEqual(order, ["begin", "start", "end", "stop"])
        self.assertEqual(stop.taid, 73)

    def test_subscription_stops_taid_when_end_fails(self):
        order = []

        class Begin:
            def __call__(self, taid_ptr, error):
                order.append("begin")
                taid_ptr._obj.value = 91
                return 1

        class Start:
            def __call__(self, *args):
                order.append("start")
                return 1

        class End:
            def __call__(self, taid, error):
                order.append("end")
                error._obj.szErrorText = "commit failed"
                return 0

        class Stop:
            def __call__(self, taid, error):
                order.append("stop")
                return 1

        fake_dm = type("FakeDM", (), {
            "DMBeginStartVarUpdateW": Begin(),
            "DMStartVarUpdateExW": Start(),
            "DMEndStartVarUpdateW": End(),
            "DMStopVarUpdateW": Stop(),
        })()
        api = WinCCRuntimeAPI(dmclient=fake_dm, configure=False)

        with self.assertRaisesRegex(RuntimeError, "commit failed"):
            api.start_updates(["LV-KW"], lambda batch: None, cycle=2)

        self.assertEqual(order, ["begin", "start", "end", "stop"])
        self.assertEqual(len(api._retired_subscriptions), 1)
        self.assertIsNotNone(api._retired_subscriptions[0].callback)

    def test_disconnect_failure_keeps_callback_references_pinned(self):
        class Disconnect:
            def __call__(self, error):
                error._obj.szErrorText = "disconnect failed"
                return 0

        fake_dm = type("FakeDM", (), {"DMDisConnectW": Disconnect()})()
        api = WinCCRuntimeAPI(dmclient=fake_dm, configure=False)
        pinned = object()
        api._connected = True
        api._retired_subscriptions.append(pinned)

        with self.assertRaisesRegex(RuntimeError, "disconnect failed"):
            api.disconnect()

        self.assertTrue(api._connected)
        self.assertEqual(api._retired_subscriptions, [pinned])

    def test_callback_contains_consumer_exceptions(self):
        class Begin:
            def __call__(self, taid_ptr, error):
                taid_ptr._obj.value = 17
                return 1

        class Start:
            def __call__(self, taid, keys, items, cycle, callback, user, error):
                update = DMVarUpdateExW()
                update.dmVarKey.szName = "LV-KW"
                update.dmValue.vt = 4
                update.dmValue.fltVal = 2.41
                update.dwState = 0
                update.dwQualityCode = 192
                self.result = callback(taid, ctypes.pointer(update), 1, user)
                return 1

        class Success:
            def __call__(self, *args):
                return 1

        start = Start()
        fake_dm = type("FakeDM", (), {
            "DMBeginStartVarUpdateW": Begin(),
            "DMStartVarUpdateExW": start,
            "DMEndStartVarUpdateW": Success(),
            "DMStopVarUpdateW": Success(),
        })()
        api = WinCCRuntimeAPI(dmclient=fake_dm, configure=False)

        subscription = api.start_updates(
            ["LV-KW"],
            lambda batch: (_ for _ in ()).throw(RuntimeError("consumer failed")),
            cycle=2,
        )

        self.assertEqual(start.result, 1)
        self.assertEqual(subscription.stats["errors"], 1)
        api.stop_updates(subscription)

    def test_station2_curated_specs_include_verified_hv_and_lv_phase_tags(self):
        specs = {
            spec["name"]: spec
            for spec in wincc_runtime.STATION2_CURATED_SPECS
        }
        expected_keys = {
            "HV-Hz": ("hv_F",),
            "HV-IA": ("hv_I1",),
            "HV-IB": ("hv_I2",),
            "HV-IC": ("hv_I3",),
            "HV-Itb": ("hv_I_avg",),
            "HV-KVA": ("hv_S",),
            "HV-KVAh": ("hv_KVAh",),
            "HV-KVAr": ("hv_Q",),
            "HV-KW": ("hv_P",),
            "HV-KWh": ("hv_KWh",),
            "HV-PF": ("hv_PF",),
            "HV-UA": ("hv_U1N",),
            "HV-UB": ("hv_U2N",),
            "HV-UC": ("hv_U3N",),
            "HV-UAB": ("hv_U12",),
            "HV-UBC": ("hv_U23",),
            "HV-UCA": ("hv_U31",),
            "HV-Uptb": ("hv_U_avg",),
            "HV-Utb": ("hv_U_ln_avg",),
            "LV-UA": ("bus_U1N", "lv_U1N"),
            "LV-UB": ("bus_U2N", "lv_U2N"),
            "LV-UC": ("bus_U3N", "lv_U3N"),
            "LV-Utb": ("bus_U_ln_avg", "lv_U_ln_avg"),
        }
        expected_bounds = {
            "HV-Hz": (45.0, 55.0, False),
            "HV-IA": (0.0, 10000.0, False),
            "HV-IB": (0.0, 10000.0, False),
            "HV-IC": (0.0, 10000.0, False),
            "HV-Itb": (0.0, 10000.0, False),
            "HV-KVA": (0.0, 100.0, False),
            "HV-KVAh": (0.0, 1.0e9, False),
            "HV-KVAr": (-100.0, 100.0, False),
            "HV-KW": (-100.0, 100.0, False),
            "HV-KWh": (0.0, 1.0e9, False),
            "HV-PF": (-1.05, 1.05, True),
            "HV-UA": (0.0, 1000.0, False),
            "HV-UB": (0.0, 1000.0, False),
            "HV-UC": (0.0, 1000.0, False),
            "HV-UAB": (0.0, 1000.0, False),
            "HV-UBC": (0.0, 1000.0, False),
            "HV-UCA": (0.0, 1000.0, False),
            "HV-Uptb": (0.0, 1000.0, False),
            "HV-Utb": (0.0, 1000.0, False),
            "LV-UA": (0.0, 50.0, False),
            "LV-UB": (0.0, 50.0, False),
            "LV-UC": (0.0, 50.0, False),
            "LV-Utb": (0.0, 50.0, False),
        }

        self.assertEqual(len(specs), 209)
        self.assertEqual(
            sum(len(spec["keys"]) for spec in specs.values()), 228)
        for source_name, canonical_keys in expected_keys.items():
            self.assertIn(source_name, specs)
            self.assertEqual(specs[source_name]["keys"], canonical_keys)
            self.assertFalse(specs[source_name]["required"])
            low, high, absolute = expected_bounds[source_name]
            self.assertEqual(specs[source_name]["min"], low)
            self.assertEqual(specs[source_name]["max"], high)
            self.assertEqual(bool(specs[source_name].get("absolute")), absolute)

    def test_station2_curated_specs_include_live_verified_scada_tags(self):
        specs = {
            spec["name"]: spec
            for spec in wincc_runtime.STATION2_CURATED_SPECS
        }
        expected = {
            "471close": (("scada_471_close_raw",), 0.0, 1.0),
            "H1QFclose": (("u1_qf_close_raw",), 0.0, 1.0),
            "H2QFclose": (("u2_qf_close_raw",), 0.0, 1.0),
            "H3QFclose": (("u3_qf_close_raw",), 0.0, 1.0),
            "H1comgroup1": (("u1_comgroup_raw",), 0.0, 65535.0),
            "H2comgroup1": (("u2_comgroup_raw",), 0.0, 65535.0),
            "H3comgroup0": (("u3_comgroup_raw",), 0.0, 65535.0),
            "AUX_LCU41_IW0": (("scada_aux_lcu41_iw0_raw",), 0.0, 65535.0),
            "OpenFull": (("scada_open_full_raw",), 0.0, 1.0),
            "CloseFull": (("scada_close_full_raw",), 0.0, 1.0),
            "MotorStatus": (("scada_motor_status_raw",), 0.0, 1.0),
            "Quatai": (("scada_overload_raw",), 0.0, 1.0),
            "Loipha": (("scada_phase_fault_raw",), 0.0, 1.0),
            "remoterlocal": (("scada_remote_local_raw",), 0.0, 1.0),
            "Domo": (("scada_opening_raw",), 0.0, 120.0),
            "Apsuat1": (("scada_pressure_1_raw",), -100.0, 100.0),
            "Apsuat2": (("scada_pressure_2_raw",), -100.0, 100.0),
            "Apsuatcao": (("scada_high_pressure_raw",), 0.0, 1.0),
            "apKTH1": (("u1_excitation_voltage_raw",), 0.0, 1000.0),
            "apKTH2": (("u2_excitation_voltage_raw",), 0.0, 1000.0),
            "apKTH3": (("u3_excitation_voltage_raw",), 0.0, 1000.0),
            "dongKTH1": (("u1_excitation_current_raw",), 0.0, 1000.0),
            "dongKTH2": (("u2_excitation_current_raw",), 0.0, 1000.0),
            "dongKTH3": (("u3_excitation_current_raw",), 0.0, 1000.0),
        }

        for source_name, (keys, low, high) in expected.items():
            self.assertIn(source_name, specs)
            self.assertEqual(specs[source_name]["keys"], keys)
            self.assertEqual(specs[source_name]["min"], low)
            self.assertEqual(specs[source_name]["max"], high)
            self.assertFalse(specs[source_name]["required"])

    def test_station2_curated_specs_include_only_phase4_runtime_proven_tags(self):
        specs = {
            spec["name"]: spec
            for spec in wincc_runtime.STATION2_CURATED_SPECS
        }
        expected = {
            "ACfrequency": (("mhy2_ac_frequency_raw",), 0.0, 100.0),
            "outfrequency": (("mhy2_output_frequency_raw",), 0.0, 100.0),
            "Outvoltage": (("mhy2_output_voltage_raw",), 0.0, 1000.0),
            "DCinput": (("mhy2_dc_input_raw",), 0.0, 1000.0),
            "ACviltagein": (("mhy2_ac_input_voltage_raw",), 0.0, 1000.0),
            "powerout": (("mhy2_output_power_raw",), 0.0, 100.0),
            "Outcurent": (("mhy2_output_current_raw",), 0.0, 1000.0),
            "tempin": (("mhy2_input_temperature_raw",), -50.0, 200.0),
            "tempout": (("mhy2_output_temperature_raw",), -50.0, 200.0),
            "DCfault": (("mhy2_dc_fault_raw",), 0.0, 1.0),
            "H1Spare19": (("mhy2_h1_spare19_raw",), 0.0, 1.0),
            "Warning": (("mhy2_warning_raw",), 0.0, 65535.0),
            "H1comgroup2": (("u1_start_secondary_group_raw",), 0.0, 65535.0),
            "H2comgroup2": (("u2_start_secondary_group_raw",), 0.0, 65535.0),
            "H3comgroup1": (("u3_start_secondary_group_raw",), 0.0, 65535.0),
            "H1Brakeoff": (("u1_brake_off_raw",), 0.0, 1.0),
            "H2Brakeoff": (("u2_brake_off_raw",), 0.0, 1.0),
            "H3Brakeoff": (("u3_brake_off_raw",), 0.0, 1.0),
            "H1local": (("u1_local_raw",), 0.0, 1.0),
            "H2local": (("u2_local_raw",), 0.0, 1.0),
            "H3local": (("u3_local_raw",), 0.0, 1.0),
            "H1remote": (("u1_remote_raw",), 0.0, 1.0),
            "H2remote": (("u2_remote_raw",), 0.0, 1.0),
            "H3remote": (("u3_remote_raw",), 0.0, 1.0),
            "H1Spare7": (("u1_spare7_raw",), 0.0, 1.0),
            "H2Spare7": (("u2_spare7_raw",), 0.0, 1.0),
            "H3Spare7": (("u3_spare7_raw",), 0.0, 1.0),
            "H1DeExcitff": (("u1_de_excitff_raw",), 0.0, 1.0),
            "H2DeExcitff": (("u2_de_excitff_raw",), 0.0, 1.0),
            "H3DeExcitff": (("u3_de_excitff_raw",), 0.0, 1.0),
            "H2Brakeopen": (("u2_brake_open_raw",), 0.0, 1.0),
            "H3Brakeopen": (("u3_brake_open_raw",), 0.0, 1.0),
            "H1Startsyn": (("u1_start_syn_raw",), 0.0, 1.0),
            "H2Startsyn": (("u2_start_syn_raw",), 0.0, 1.0),
            "H3Startsyn": (("u3_start_syn_raw",), 0.0, 1.0),
            "H1Spristore": (("u1_spri_store_raw",), 0.0, 1.0),
            "H2Spristore": (("u2_spri_store_raw",), 0.0, 1.0),
            "H3Spristore": (("u3_spri_store_raw",), 0.0, 1.0),
            "H1Springcharg": (("u1_spring_charg_raw",), 0.0, 1.0),
            "H2Springcharg": (("u2_spring_charg_raw",), 0.0, 1.0),
            "H3Springcharg": (("u3_spring_charg_raw",), 0.0, 1.0),
            "H1MVopen": (("u1_mv_open_raw",), 0.0, 1.0),
            "H2MVopen": (("u2_mv_open_raw",), 0.0, 1.0),
            "H3MVopen": (("u3_mv_open_raw",), 0.0, 1.0),
            "H1MVclose": (("u1_mv_close_raw",), 0.0, 1.0),
            "H2MVclose": (("u2_mv_close_raw",), 0.0, 1.0),
            "H3MVclose": (("u3_mv_close_raw",), 0.0, 1.0),
            "realopening1": (("u1_real_opening_raw",), 0.0, 120.0),
            "realopening2": (("u2_real_opening_raw",), 0.0, 120.0),
            "realopening3": (("u3_real_opening_raw",), 0.0, 120.0),
            "H2-Frequ": (("u2_start_frequency_raw",), 0.0, 100.0),
            "H3-Frequ": (("u3_start_frequency_raw",), 0.0, 100.0),
        }

        self.assertEqual(len(expected), 52)
        self.assertEqual(len(specs), 209)
        self.assertEqual(sum(len(spec["keys"]) for spec in specs.values()), 228)
        self.assertLessEqual(len(specs), 256)
        for source_name, (keys, low, high) in expected.items():
            self.assertIn(source_name, specs)
            self.assertEqual(specs[source_name]["keys"], keys)
            self.assertEqual(specs[source_name]["min"], low)
            self.assertEqual(specs[source_name]["max"], high)
            self.assertFalse(specs[source_name]["required"])
            self.assertEqual(
                specs[source_name]["project_files"],
                wincc_runtime.DAKROSA2_RUNTIME_PROJECT_FILES,
            )

        for excluded in (
            "DCTC-",
            "H1OpMvalve", "H2OpMvalve", "H3OpMvalve",
            "H1Opvalve", "H2Opvalve", "H3Opvalve",
        ):
            self.assertNotIn(excluded, specs)

    def test_station2_curated_specs_add_neutral_phase5_connect_raw(self):
        specs = {
            spec["name"]: spec
            for spec in wincc_runtime.STATION2_CURATED_SPECS
        }

        self.assertEqual(specs["Connect"]["keys"], ("scada_connect_raw",))
        self.assertEqual(specs["Connect"]["min"], 0.0)
        self.assertEqual(specs["Connect"]["max"], 1.0)
        self.assertEqual(specs["Connect"]["allowed_values"], (0.0, 1.0))
        self.assertFalse(specs["Connect"]["required"])
        self.assertEqual(
            specs["Connect"]["project_files"],
            wincc_runtime.DAKROSA2_RUNTIME_PROJECT_FILES,
        )
        self.assertNotIn(
            "scada_connect_fault_raw",
            {
                key
                for spec in wincc_runtime.STATION2_CURATED_SPECS
                for key in spec["keys"]
            },
        )

    def test_phase4_curated_tags_require_the_reviewed_runtime_project(self):
        class ProjectAPI:
            def __init__(self, project):
                self.project = project
                self.names = []

            def connect(self):
                pass

            def disconnect(self):
                pass

            def runtime_project(self):
                return self.project

            def read_numerics(self, names, type_code):
                self.names = list(names)
                return {
                    name: {"value": 50.0, "state": 0, "quality": None}
                    for name in names
                }

        reviewed = ProjectAPI(
            r"C:\SCADA\WInCC_Backup_30_10_2020.mcp")
        reviewed_result = read_curated_snapshot(
            "Dakrosa2", "2026-07-14T12:00:00Z",
            api_factory=lambda: reviewed,
        )
        self.assertIn("H2-Frequ", reviewed.names)
        self.assertEqual(
            reviewed_result["tags"]["u2_start_frequency_raw"]["last"],
            50.0,
        )
        self.assertIn("u2_F", reviewed_result["tags"])
        self.assertNotIn("u2_GV", reviewed_result["tags"])

        other = ProjectAPI(r"C:\SCADA\Dakrosa2\Unknown.mcp")
        other_result = read_curated_snapshot(
            "Dakrosa2", "2026-07-14T12:00:00Z",
            api_factory=lambda: other,
        )
        self.assertNotIn("H2-Frequ", other.names)
        self.assertNotIn("u2_start_frequency_raw", other_result["tags"])
        self.assertEqual(other_result["project_gated_skipped"], 69)

    def test_phase5_connect_maps_only_healthy_binary_runtime_values(self):
        class ConnectAPI:
            def __init__(self, value=1, state=0):
                self.value = value
                self.state = state

            def connect(self):
                pass

            def disconnect(self):
                pass

            def runtime_project(self):
                return r"C:\SCADA\WInCC_Backup_30_10_2020.mcp"

            def read_numerics(self, names, type_code):
                return {
                    "Connect": {
                        "value": self.value,
                        "state": self.state,
                        "quality": None,
                    },
                }

        healthy = read_curated_snapshot(
            "Dakrosa2",
            "2026-07-14T15:00:00Z",
            api_factory=lambda: ConnectAPI(),
        )
        self.assertEqual(healthy["tags"]["scada_connect_raw"]["last"], 1.0)
        self.assertNotIn("scada_connect_fault_raw", healthy["tags"])

        bad_state = read_curated_snapshot(
            "Dakrosa2",
            "2026-07-14T15:00:01Z",
            api_factory=lambda: ConnectAPI(state=257),
        )
        self.assertNotIn("scada_connect_raw", bad_state["tags"])

        bad_value = read_curated_snapshot(
            "Dakrosa2",
            "2026-07-14T15:00:02Z",
            api_factory=lambda: ConnectAPI(value=2),
        )
        self.assertNotIn("scada_connect_raw", bad_value["tags"])

        fractional_value = read_curated_snapshot(
            "Dakrosa2",
            "2026-07-14T15:00:02Z",
            api_factory=lambda: ConnectAPI(value=0.5),
        )
        self.assertNotIn("scada_connect_raw", fractional_value["tags"])

        station1 = read_curated_snapshot(
            "Dakrosa1",
            "2026-07-14T15:00:03Z",
            api_factory=lambda: ConnectAPI(),
        )
        self.assertEqual(station1["attempted"], 0)
        self.assertNotIn("scada_connect_raw", station1["tags"])

    def test_phase4_snapshot_maps_valid_samples_without_semantic_aliases(self):
        class Phase4API:
            def connect(self):
                pass

            def disconnect(self):
                pass

            def runtime_project(self):
                return r"C:\SCADA\WInCC_Backup_30_10_2020.mcp"

            def read_numerics(self, names, type_code):
                self.names = list(names)
                return {
                    "ACfrequency": {
                        "value": 49.8, "state": 0, "quality": None},
                    "DCfault": {
                        "value": 1, "state": 0, "quality": None},
                    "Warning": {
                        "value": 322, "state": 0, "quality": None},
                    "powerout": {
                        "value": 100, "state": 0, "quality": None},
                    "realopening2": {
                        "value": 45.5, "state": 0, "quality": None},
                    "H2-Frequ": {
                        "value": 50.1, "state": 0, "quality": None},
                    "Outcurent": {
                        "value": 1200, "state": 0, "quality": None},
                    "H2Brakeoff": {
                        "value": 1, "state": 257, "quality": None},
                    "H3-Frequ": {
                        "value": float("nan"), "state": 0,
                        "quality": None},
                }

        result = read_curated_snapshot(
            "Dakrosa2", "2026-07-14T12:10:00Z", api_factory=Phase4API)

        self.assertEqual(result["accepted"], 6)
        self.assertEqual(result["project_gated_skipped"], 0)
        self.assertEqual(
            result["tags"]["mhy2_ac_frequency_raw"]["last"], 49.8)
        self.assertEqual(result["tags"]["mhy2_dc_fault_raw"]["last"], 1.0)
        self.assertEqual(result["tags"]["mhy2_warning_raw"]["last"], 322.0)
        self.assertEqual(
            result["tags"]["mhy2_output_power_raw"]["last"], 100.0)
        self.assertEqual(result["tags"]["u2_real_opening_raw"]["last"], 45.5)
        self.assertEqual(
            result["tags"]["u2_start_frequency_raw"]["last"], 50.1)
        self.assertNotIn("mhy2_output_current_raw", result["tags"])
        self.assertNotIn("u2_brake_off_raw", result["tags"])
        self.assertNotIn("u3_start_frequency_raw", result["tags"])
        self.assertNotIn("u2_F", result["tags"])
        self.assertNotIn("u2_GV", result["tags"])

        class OverloadAPI(Phase4API):
            def read_numerics(self, names, type_code):
                return {
                    "powerout": {
                        "value": 100.1, "state": 0, "quality": None},
                }

        overloaded = read_curated_snapshot(
            "Dakrosa2", "2026-07-14T12:11:00Z",
            api_factory=OverloadAPI)
        self.assertNotIn("mhy2_output_power_raw", overloaded["tags"])

    def test_curated_station2_snapshot_maps_only_valid_realtime_values(self):
        class SelectedAPI:
            def __init__(self):
                self.connected = False
                self.disconnected = False
                self.values = {
                    "H1-Hz": {"value": 50.25, "state": 0, "quality": None},
                    "H1-IA": {"value": 1120.0, "state": 257, "quality": None},
                    "H1_temp1": {"value": 48.5, "state": 0, "quality": None},
                    "H1_temp2": {"value": -2.03, "state": 0, "quality": None},
                    "LV-KW": {"value": 2.41, "state": 0, "quality": None},
                    "LV-PF": {"value": -0.999, "state": 0, "quality": None},
                    "LV-UAB": {"value": 23.8, "state": 0, "quality": None},
                    "LV-UA": {"value": 13.58, "state": 0, "quality": None},
                    "HV-KW": {"value": 2.43, "state": 0, "quality": None},
                    "HV-UA": {"value": 230.1, "state": 0, "quality": None},
                    "HV-UAB": {"value": 399.4, "state": 0, "quality": None},
                    "HV-IB": {"value": 3650.0, "state": 257, "quality": None},
                    "HV-IC": {"value": 3525.0, "state": 0.5, "quality": None},
                    "LV-UB": {"value": 13580.0, "state": 0, "quality": None},
                    "H1QFclose": {"value": 0, "state": 0, "quality": None},
                    "H2QFclose": {"value": 2, "state": 0, "quality": None},
                    "AUX_LCU41_IW0": {"value": 0, "state": 257, "quality": None},
                    "Domo": {
                        "value": 110.9259262084961,
                        "state": 0,
                        "quality": None,
                    },
                    "Apsuat2": {"value": -0.77, "state": 0, "quality": None},
                    "apKTH1": {"value": 25.2, "state": 0, "quality": None},
                    "dongKTH1": {"value": 0.33, "state": 0, "quality": None},
                }

            def connect(self):
                self.connected = True

            def disconnect(self):
                self.disconnected = True

            def read_numeric(self, name, type_code):
                self.asserted_type = type_code
                if name not in self.values:
                    raise RuntimeError("not configured")
                return self.values[name]

        api = SelectedAPI()

        result = read_curated_snapshot(
            "Dakrosa2",
            "2026-07-10T04:10:00Z",
            api_factory=lambda: api,
        )

        self.assertTrue(result["available"])
        self.assertTrue(api.connected)
        self.assertTrue(api.disconnected)
        self.assertEqual(result["tags"]["u1_F"]["last"], 50.25)
        self.assertEqual(result["tags"]["u1_temp1"]["last"], 48.5)
        self.assertEqual(result["tags"]["bus_P"]["last"], 2.41)
        self.assertEqual(result["tags"]["lv_P"]["last"], 2.41)
        self.assertEqual(result["tags"]["bus_PF"]["last"], 0.999)
        self.assertEqual(result["tags"]["bus_U12"]["last"], 23.8)
        self.assertEqual(result["tags"]["bus_U1N"]["last"], 13.58)
        self.assertEqual(result["tags"]["lv_U1N"]["last"], 13.58)
        self.assertEqual(result["tags"]["hv_P"]["last"], 2.43)
        self.assertEqual(result["tags"]["hv_U1N"]["last"], 230.1)
        self.assertEqual(result["tags"]["hv_U12"]["last"], 399.4)
        self.assertNotIn("hv_I2", result["tags"])
        self.assertNotIn("hv_I3", result["tags"])
        self.assertNotIn("bus_U2N", result["tags"])
        self.assertNotIn("u1_I1", result["tags"])
        self.assertNotIn("u1_temp2", result["tags"])
        self.assertEqual(result["tags"]["u1_qf_close_raw"]["last"], 0.0)
        self.assertEqual(
            result["tags"]["scada_opening_raw"]["last"],
            110.9259262084961,
        )
        self.assertEqual(result["tags"]["scada_pressure_2_raw"]["last"], -0.77)
        self.assertEqual(result["tags"]["u1_excitation_voltage_raw"]["last"], 25.2)
        self.assertEqual(result["tags"]["u1_excitation_current_raw"]["last"], 0.33)
        self.assertNotIn("u2_qf_close_raw", result["tags"])
        self.assertNotIn("scada_aux_lcu41_iw0_raw", result["tags"])
        self.assertEqual(result["tags"]["u1_F"]["source"], "wincc-dmclient")
        self.assertTrue(result["tags"]["u1_F"]["realtime"])
        self.assertGreater(result["rejected"], 0)

    def test_curated_snapshot_leaves_unknown_station_on_archive_fallback(self):
        factory = mock.Mock()

        result = read_curated_snapshot(
            "Dakrosa1", "2026-07-10T04:10:00Z", api_factory=factory)

        self.assertFalse(result["available"])
        self.assertFalse(result["supported"])
        factory.assert_not_called()

    def test_curated_snapshot_prefers_one_bounded_batch_read(self):
        class BatchAPI:
            def connect(self):
                pass

            def disconnect(self):
                pass

            def read_numerics(self, names, type_code):
                self.names = names
                self.type_code = type_code
                return {
                    "Tag-A": {"value": 10.0, "state": 0, "quality": None},
                    "Tag-B": {"value": 20.0, "state": 0, "quality": None},
                }

            def read_numeric(self, name, type_code):
                raise AssertionError("sequential read should not be used")

        api = BatchAPI()
        specs = (
            {"name": "Tag-A", "keys": ("a",), "min": 0, "max": 100},
            {"name": "Tag-B", "keys": ("b",), "min": 0, "max": 100},
        )

        result = read_curated_snapshot(
            "Dakrosa2", "2026-07-10T04:30:00Z",
            api_factory=lambda: api, specs=specs)

        self.assertEqual(api.names, ["Tag-A", "Tag-B"])
        self.assertEqual(api.type_code, 8)
        self.assertEqual(result["accepted"], 2)

    def test_curated_snapshot_counts_optional_failures_separately_from_core(self):
        class BatchAPI:
            def connect(self):
                pass

            def disconnect(self):
                pass

            def read_numerics(self, names, type_code):
                return {
                    "Core-Tag": {"value": 10.0, "state": 0, "quality": None},
                }

        specs = (
            {"name": "Core-Tag", "keys": ("core",), "min": 0, "max": 100},
            {"name": "Optional-Tag", "keys": ("optional",), "min": 0,
             "max": 100, "required": False},
        )

        result = read_curated_snapshot(
            "Dakrosa2", "2026-07-10T04:30:00Z",
            api_factory=BatchAPI, specs=specs)

        self.assertEqual(result["attempted"], 2)
        self.assertEqual(result["accepted"], 1)
        self.assertEqual(result["required_attempted"], 1)
        self.assertEqual(result["required_accepted"], 1)
        self.assertNotIn("optional", result["tags"])

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

    def test_candidate_filter_prioritizes_telemetry_over_system_and_alarm_tags(self):
        tags = [
            {"id": 1, "name": "@AlarmComeGone_H1"},
            {"id": 2, "name": "Alarm_MatnguonAC_H1"},
            {"id": 3, "name": "H1_GeneratorPower_kW"},
            {"id": 4, "name": "H1_BearingTemp_1"},
        ]

        selected = select_candidate_tags(tags, limit=2)

        self.assertEqual(
            [tag["name"] for tag in selected],
            ["H1_BearingTemp_1", "H1_GeneratorPower_kW"],
        )

    def test_probe_returns_inventory_and_quality_aware_candidate_values(self):
        api = FakeRuntimeAPI()

        result = build_probe(api, inventory_limit=100, candidate_limit=20)

        self.assertTrue(result["available"])
        self.assertEqual(result["backend"], "wincc-dmclient")
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

    def test_metadata_probe_enumerates_candidates_without_reading_values(self):
        api = FakeRuntimeAPI()

        result = build_probe(
            api, inventory_limit=0, candidate_limit=20, read_values=False)

        self.assertTrue(result["available"])
        self.assertEqual(len(result["candidates"]), 4)
        self.assertEqual(api.read_names, [])
        self.assertNotIn("value", result["candidates"][0])

    def test_probe_reads_only_explicit_scada_diagnostic_tags(self):
        class ScadaAPI(FakeRuntimeAPI):
            def enumerate_tags(self, project):
                return [
                    {"id": 101, "name": "H1QFclose"},
                    {"id": 102, "name": "Apsuat1"},
                    {"id": 103, "name": "ClickH1"},
                ]

            def tag_type(self, project, tag):
                if tag["name"] == "H1QFclose":
                    return {"code": 1, "name": "Binary Tag", "size": 1}
                return {"code": 8, "name": "Float", "size": 4}

            def read_numeric(self, name, type_code):
                self.read_names.append(name)
                values = {"H1QFclose": 1, "Apsuat1": 3.25}
                return {"value": values[name], "state": 0, "quality": None}

        api = ScadaAPI()
        result = build_probe(
            api,
            inventory_limit=0,
            candidate_limit=0,
            exact_names=("h1qfclose", "Apsuat1", "MissingStatus", "ClickH1"),
        )

        exact = result["exact"]
        self.assertEqual(exact["requested"], 4)
        self.assertEqual(exact["found"], 2)
        self.assertEqual(exact["missing"], ["MissingStatus"])
        self.assertEqual(exact["denied"], ["ClickH1"])
        self.assertEqual(
            [(item["name"], item["type_code"], item["value"])
             for item in exact["tags"]],
            [("H1QFclose", 1, 1), ("Apsuat1", 8, 3.25)],
        )
        self.assertEqual(api.read_names, ["H1QFclose", "Apsuat1"])
        self.assertNotIn("ClickH1", api.read_names)

    def test_scada_exact_probe_defaults_empty_and_is_gated_to_dakrosa2(self):
        class StationAPI:
            def __init__(self, project):
                self.project = project
                self.read_names = []

            def connect(self):
                pass

            def disconnect(self):
                pass

            def runtime_project(self):
                return self.project

            def enumerate_tags(self, project):
                return [{"id": 101, "name": "H1QFclose"}]

            def tag_type(self, project, tag):
                return {"code": 1, "name": "Binary Tag", "size": 1}

            def read_numeric(self, name, type_code):
                self.read_names.append(name)
                return {"value": 1, "state": 0, "quality": None}

        generic = StationAPI(r"C:\SCADA\Other\Other.mcp")
        generic_result = build_probe(
            generic, inventory_limit=0, candidate_limit=0)
        self.assertEqual(generic_result["exact"]["requested"], 0)
        self.assertEqual(generic.read_names, [])

        station1 = StationAPI(r"C:\SCADA\Dakrosa1\Dakrosa1.mcp")
        result1 = probe_runtime(
            api_factory=lambda: station1,
            station_name="Dakrosa1",
            inventory_limit=0,
            candidate_limit=0,
        )
        self.assertEqual(result1["exact"]["requested"], 0)
        self.assertEqual(station1.read_names, [])

        station2 = StationAPI(
            r"C:\SCADA\Dakrosa2\WInCC_Backup_30_10_2020.mcp")
        result2 = probe_runtime(
            api_factory=lambda: station2,
            station_name="Dakrosa2",
            inventory_limit=0,
            candidate_limit=0,
        )
        self.assertGreater(result2["exact"]["requested"], 0)
        self.assertEqual(station2.read_names, ["H1QFclose"])

        mismatched = StationAPI(r"C:\SCADA\Dakrosa1\Dakrosa1.mcp")
        mismatch_result = probe_runtime(
            api_factory=lambda: mismatched,
            station_name="Dakrosa2",
            inventory_limit=0,
            candidate_limit=0,
        )
        self.assertEqual(mismatch_result["exact"]["requested"], 0)
        self.assertEqual(mismatched.read_names, [])

        unknown_project = StationAPI(r"C:\SCADA\Dakrosa2\Dakrosa2.mcp")
        unknown_result = probe_runtime(
            api_factory=lambda: unknown_project,
            station_name="Dakrosa2",
            inventory_limit=0,
            candidate_limit=0,
        )
        self.assertEqual(unknown_result["exact"]["requested"], 0)
        self.assertEqual(unknown_project.read_names, [])

    def test_default_scada_diagnostic_allowlist_excludes_command_tags(self):
        folded = {name.lower() for name in wincc_runtime.SCADA_DIAGNOSTIC_TAGS}

        self.assertTrue({"471close", "h1qfclose", "h2qfclose", "h3qfclose"} <= folded)
        self.assertTrue({"apsuat1", "apsuat2", "domo"} <= folded)
        self.assertFalse(any(name.startswith("click") for name in folded))

    def test_mhy2_diagnostic_allowlist_matches_recovered_read_only_sources(self):
        self.assertEqual(
            wincc_runtime.MHY2_DIAGNOSTIC_TAGS,
            (
                "ACfrequency",
                "outfrequency",
                "Outvoltage",
                "DCTC-",
                "DCinput",
                "ACviltagein",
                "powerout",
                "Outcurent",
                "tempin",
                "tempout",
                "DCfault",
                "H1Spare19",
                "Warning",
            ),
        )

    def test_start_sequence_diagnostic_allowlist_matches_recovered_sources(self):
        self.assertEqual(
            wincc_runtime.START_SEQUENCE_DIAGNOSTIC_TAGS,
            (
                "H1comgroup2", "H2comgroup2", "H3comgroup1",
                "H1Brakeoff", "H2Brakeoff", "H3Brakeoff",
                "H1local", "H2local", "H3local",
                "H1remote", "H2remote", "H3remote",
                "H1Spare7", "H2Spare7", "H3Spare7",
                "H1OpMvalve", "H2OpMvalve", "H3OpMvalve",
                "H1Opvalve", "H2Opvalve", "H3Opvalve",
                "H1DeExcitff", "H2DeExcitff", "H3DeExcitff",
                "H2Brakeopen", "H3Brakeopen",
                "H1Startsyn", "H2Startsyn", "H3Startsyn",
                "H1Spristore", "H2Spristore", "H3Spristore",
                "H1Springcharg", "H2Springcharg", "H3Springcharg",
                "H1MVopen", "H2MVopen", "H3MVopen",
                "H1MVclose", "H2MVclose", "H3MVclose",
                "realopening1", "realopening2", "realopening3",
                "H2-Frequ", "H3-Frequ",
            ),
        )

    def test_operator_diagnostic_allowlist_is_exact_and_not_canonical(self):
        self.assertEqual(
            wincc_runtime.OPERATOR_DIAGNOSTIC_TAGS,
            (
                "EVENT_TYPE_MH1",
                "EVENT_TYPE_MH2",
                "EVENT_TYPE_MH3",
            ),
        )
        canonical_sources = {
            spec["name"] for spec in wincc_runtime.STATION2_CURATED_SPECS
        }
        self.assertTrue(
            set(wincc_runtime.OPERATOR_DIAGNOSTIC_TAGS).isdisjoint(
                canonical_sources
            )
        )

    def test_h2_directional_energy_diagnostics_are_exact_and_not_canonical(self):
        self.assertEqual(
            wincc_runtime.H2_DIRECTIONAL_ENERGY_DIAGNOSTIC_TAGS,
            (
                "MWHPX_INTER_MH2",
                "MWHNX_INTER_MH2",
                "MVARHPX_INTER_MH2",
                "MVARHNX_INTER_MH2",
            ),
        )
        canonical_sources = {
            spec["name"] for spec in wincc_runtime.STATION2_CURATED_SPECS
        }
        self.assertTrue(
            set(
                wincc_runtime.H2_DIRECTIONAL_ENERGY_DIAGNOSTIC_TAGS
            ).isdisjoint(canonical_sources)
        )

    def test_h2_directional_energy_diagnostics_read_only_on_reviewed_project(self):
        class DirectionalEnergyAPI:
            def __init__(self, project):
                self.project = project
                self.read_names = []

            def connect(self):
                pass

            def disconnect(self):
                pass

            def runtime_project(self):
                return self.project

            def enumerate_tags(self, project):
                return [
                    {"id": index, "name": name}
                    for index, name in enumerate(
                        wincc_runtime.H2_DIRECTIONAL_ENERGY_DIAGNOSTIC_TAGS,
                        1,
                    )
                ]

            def tag_type(self, project, tag):
                return {"code": 8, "name": "Float", "size": 4}

            def read_numeric(self, name, type_code):
                self.read_names.append(name)
                values = {
                    "MWHPX_INTER_MH2": 101.0,
                    "MWHNX_INTER_MH2": 2.0,
                    "MVARHPX_INTER_MH2": 33.0,
                    "MVARHNX_INTER_MH2": 4.0,
                }
                return {"value": values[name], "state": 0, "quality": None}

        reviewed = DirectionalEnergyAPI(
            r"C:\SCADA\Dakrosa2\WInCC_Backup_30_10_2020.mcp"
        )
        result = probe_runtime(
            api_factory=lambda: reviewed,
            station_name="Dakrosa2",
            inventory_limit=0,
            candidate_limit=0,
        )

        self.assertEqual(result["exact"]["requested"], 90)
        self.assertEqual(result["exact"]["found"], 4)
        self.assertEqual(
            [item["name"] for item in result["exact"]["tags"]],
            list(wincc_runtime.H2_DIRECTIONAL_ENERGY_DIAGNOSTIC_TAGS),
        )
        self.assertEqual(
            reviewed.read_names,
            list(wincc_runtime.H2_DIRECTIONAL_ENERGY_DIAGNOSTIC_TAGS),
        )

        station1 = DirectionalEnergyAPI(
            r"C:\SCADA\Dakrosa2\WInCC_Backup_30_10_2020.mcp"
        )
        station1_result = probe_runtime(
            api_factory=lambda: station1,
            station_name="Dakrosa1",
            inventory_limit=0,
            candidate_limit=0,
        )
        self.assertEqual(station1_result["exact"]["requested"], 0)
        self.assertEqual(station1.read_names, [])

        mismatched = DirectionalEnergyAPI(
            r"C:\SCADA\Dakrosa2\Unexpected.mcp"
        )
        mismatch_result = probe_runtime(
            api_factory=lambda: mismatched,
            station_name="Dakrosa2",
            inventory_limit=0,
            candidate_limit=0,
        )
        self.assertEqual(mismatch_result["exact"]["requested"], 0)
        self.assertEqual(mismatched.read_names, [])

    def test_phase9_parameter_sources_are_curated_and_not_diagnostic(self):
        specs = {
            spec["name"]: spec
            for spec in wincc_runtime.STATION2_CURATED_SPECS
        }
        expected = {
            "H1_temp11": (("u1_temp11",), 5.0, 150.0),
        }
        for unit in (1, 2, 3):
            prefix = "u%d_" % unit
            expected.update({
                "H%d-KW1" % unit: (
                    (prefix + "phase_a_active_power_raw",),
                    -10000.0, 10000.0),
                "H%d-KWA1" % unit: (
                    (prefix + "phase_a_reactive_power_raw",),
                    -10000.0, 10000.0),
                "H%d-KW3" % unit: (
                    (prefix + "phase_c_active_power_raw",),
                    -10000.0, 10000.0),
                "H%d-KWA3" % unit: (
                    (prefix + "phase_c_reactive_power_raw",),
                    -10000.0, 10000.0),
                "H%d-KVArh" % unit: (
                    (prefix + "reactive_energy_raw",),
                    0.0, 1.0e9),
            })

        self.assertEqual(len(expected), 16)
        for source, (keys, low, high) in expected.items():
            self.assertEqual(specs[source]["keys"], keys)
            self.assertEqual(specs[source]["min"], low)
            self.assertEqual(specs[source]["max"], high)
            self.assertFalse(specs[source]["required"])
            self.assertEqual(
                specs[source]["project_files"],
                wincc_runtime.DAKROSA2_RUNTIME_PROJECT_FILES,
            )
            self.assertNotIn(source, wincc_runtime.SCADA_DIAGNOSTIC_TAGS)

    def test_phase9_parameter_sources_map_only_healthy_runtime_values(self):
        class ParameterAPI:
            def __init__(self, values):
                self.values = values

            def connect(self):
                pass

            def disconnect(self):
                pass

            def runtime_project(self):
                return r"C:\SCADA\Dakrosa2\WInCC_Backup_30_10_2020.mcp"

            def read_numerics(self, names, type_code):
                return self.values

        values = {
            "H1_temp11": {"value": 46.5, "state": 0, "quality": None},
        }
        for unit in (1, 2, 3):
            values.update({
                "H%d-KW1" % unit: {
                    "value": 380.0 + unit, "state": 0, "quality": None},
                "H%d-KWA1" % unit: {
                    "value": 240.0 + unit, "state": 0, "quality": None},
                "H%d-KW3" % unit: {
                    "value": 420.0 + unit, "state": 0, "quality": None},
                "H%d-KWA3" % unit: {
                    "value": -190.0 - unit, "state": 0, "quality": None},
                "H%d-KVArh" % unit: {
                    "value": 2200.0 + unit, "state": 0, "quality": None},
            })

        result = read_curated_snapshot(
            "Dakrosa2", "2026-07-14T16:00:00Z",
            api_factory=lambda: ParameterAPI(values),
        )
        self.assertEqual(result["tags"]["u1_temp11"]["last"], 46.5)
        self.assertEqual(
            result["tags"]["u2_phase_a_active_power_raw"]["last"], 382.0)
        self.assertEqual(
            result["tags"]["u3_phase_c_reactive_power_raw"]["last"], -193.0)
        self.assertEqual(
            result["tags"]["u1_reactive_energy_raw"]["last"], 2201.0)

        invalid = dict(values)
        invalid["H1_temp11"] = {
            "value": 151.0, "state": 0, "quality": None}
        invalid["H1-KVArh"] = {
            "value": -1.0, "state": 0, "quality": None}
        invalid["H2-KW1"] = {
            "value": 382.0, "state": 257, "quality": None}
        rejected = read_curated_snapshot(
            "Dakrosa2", "2026-07-14T16:00:01Z",
            api_factory=lambda: ParameterAPI(invalid),
        )
        self.assertNotIn("u1_temp11", rejected["tags"])
        self.assertNotIn("u1_reactive_energy_raw", rejected["tags"])
        self.assertNotIn("u2_phase_a_active_power_raw", rejected["tags"])

        station1 = read_curated_snapshot(
            "Dakrosa1", "2026-07-14T16:00:02Z",
            api_factory=lambda: ParameterAPI(values),
        )
        self.assertEqual(station1["attempted"], 0)
        self.assertNotIn("u1_temp11", station1["tags"])

    def test_operator_diagnostics_are_read_only_on_the_exact_dakrosa2_project(self):
        class OperatorAPI:
            def __init__(self):
                self.read_names = []

            def connect(self):
                pass

            def disconnect(self):
                pass

            def runtime_project(self):
                return r"C:\SCADA\Dakrosa2\WInCC_Backup_30_10_2020.mcp"

            def enumerate_tags(self, project):
                return [
                    {"id": 10, "name": "Connect"},
                    {"id": 40, "name": "EVENT_TYPE_MH1"},
                    {"id": 308, "name": "EVENT_TYPE_MH2"},
                    {"id": 375, "name": "EVENT_TYPE_MH3"},
                ]

            def tag_type(self, project, tag):
                if tag["name"] == "Connect":
                    return {"code": 1, "name": "Binary Tag", "size": 1}
                return {"code": 8, "name": "Float", "size": 4}

            def read_numeric(self, name, type_code):
                self.read_names.append(name)
                values = {
                    "Connect": 0,
                    "EVENT_TYPE_MH1": 11.0,
                    "EVENT_TYPE_MH2": 22.0,
                    "EVENT_TYPE_MH3": 33.0,
                }
                return {"value": values[name], "state": 0, "quality": None}

        api = OperatorAPI()
        result = probe_runtime(
            api_factory=lambda: api,
            station_name="Dakrosa2",
            inventory_limit=0,
            candidate_limit=0,
        )

        self.assertEqual(result["exact"]["requested"], 90)
        self.assertEqual(result["exact"]["found"], 3)
        self.assertEqual(result["exact"]["missing"], [
            name for name in wincc_runtime.SCADA_DIAGNOSTIC_TAGS
            if name not in wincc_runtime.OPERATOR_DIAGNOSTIC_TAGS
        ])
        self.assertEqual(
            [
                (item["name"], item["type_code"], item["value"], item["state"])
                for item in result["exact"]["tags"]
            ],
            [
                ("EVENT_TYPE_MH1", 8, 11.0, 0),
                ("EVENT_TYPE_MH2", 8, 22.0, 0),
                ("EVENT_TYPE_MH3", 8, 33.0, 0),
            ],
        )
        self.assertEqual(api.read_names, list(wincc_runtime.OPERATOR_DIAGNOSTIC_TAGS))

    def test_default_diagnostic_allowlist_contains_new_sources_once(self):
        names = wincc_runtime.SCADA_DIAGNOSTIC_TAGS
        folded = [name.lower() for name in names]

        self.assertEqual(len(names), 90)
        self.assertEqual(len(folded), len(set(folded)))
        self.assertTrue(set(wincc_runtime.MHY2_DIAGNOSTIC_TAGS) <= set(names))
        self.assertTrue(set(wincc_runtime.START_SEQUENCE_DIAGNOSTIC_TAGS) <= set(names))
        self.assertTrue(set(wincc_runtime.OPERATOR_DIAGNOSTIC_TAGS) <= set(names))
        self.assertTrue(
            set(wincc_runtime.H2_DIRECTIONAL_ENERGY_DIAGNOSTIC_TAGS) <= set(names)
        )
        self.assertFalse(any("command" in name or name.startswith("click") for name in folded))

    def test_exact_probe_hard_denies_click_and_command_channels(self):
        class CommandAPI:
            def __init__(self):
                self.read_names = []

            def runtime_project(self):
                return r"C:\SCADA\Dakrosa2\Dakrosa2.mcp"

            def enumerate_tags(self, project):
                return [
                    {"id": 1, "name": "H2-Frequ"},
                    {"id": 2, "name": "ClickH2"},
                    {"id": 3, "name": "H1command1"},
                ]

            def tag_type(self, project, tag):
                return {"code": 8, "name": "Float", "size": 4}

            def read_numeric(self, name, type_code):
                self.read_names.append(name)
                return {"value": 50.0, "state": 0, "quality": None}

        api = CommandAPI()
        result = build_probe(
            api,
            inventory_limit=0,
            candidate_limit=0,
            exact_names=("H2-Frequ", "ClickH2", "H1command1"),
        )

        self.assertEqual(result["exact"]["denied"], ["ClickH2", "H1command1"])
        self.assertEqual(api.read_names, ["H2-Frequ"])

    def test_probe_degrades_to_diagnostic_payload_instead_of_raising(self):
        class BrokenAPI:
            def runtime_project(self):
                raise RuntimeError("ODK license unavailable")

        result = build_probe(BrokenAPI())

        self.assertFalse(result["available"])
        self.assertIn("ODK license unavailable", result["error"])

    def test_ctypes_adapter_reads_float_with_state_from_data_manager(self):
        class GetValue:
            def __call__(self, key_ptr, count, update_ptr, error):
                self.name = key_ptr._obj.szName
                self.count = count
                update_ptr._obj.dmValue.vt = 4  # VT_R4
                update_ptr._obj.dmValue.fltVal = 49.98
                update_ptr._obj.dwState = 7
                return 1

        get_value = GetValue()
        fake_dm = type("FakeDM", (), {"DMGetValueW": get_value})()
        api = WinCCRuntimeAPI(dmclient=fake_dm, configure=False)

        result = api.read_numeric(r"22kV\Bus_nF", 8)

        self.assertEqual(get_value.name, r"22kV\Bus_nF")
        self.assertEqual(get_value.count, 1)
        self.assertAlmostEqual(result["value"], 49.98, places=3)
        self.assertEqual(result["state"], 7)
        self.assertIsNone(result["quality"])

    def test_ctypes_adapter_reads_selected_values_in_one_data_manager_call(self):
        class GetValues:
            def __call__(self, keys, count, updates, error):
                self.count = count
                self.names = [keys[i].szName for i in range(count)]
                for index, value in enumerate((50.125, 812.5)):
                    updates[index].dmValue.vt = 4  # VT_R4
                    updates[index].dmValue.fltVal = value
                    updates[index].dwState = 0
                return 1

        get_values = GetValues()
        fake_dm = type("FakeDM", (), {"DMGetValueW": get_values})()
        api = WinCCRuntimeAPI(dmclient=fake_dm, configure=False)

        result = api.read_numerics(["H1-Hz", "H1-KW"], 8)

        self.assertEqual(get_values.count, 2)
        self.assertEqual(get_values.names, ["H1-Hz", "H1-KW"])
        self.assertAlmostEqual(result["H1-Hz"]["value"], 50.125)
        self.assertAlmostEqual(result["H1-KW"]["value"], 812.5)

    def test_ctypes_adapter_rejects_non_numeric_types(self):
        api = WinCCRuntimeAPI(dmclient=object(), configure=False)

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
        api = WinCCRuntimeAPI(dmclient=fake_dm, configure=False)

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
        api = WinCCRuntimeAPI(dmclient=fake_dm, configure=False)

        result = api.tag_type(
            r"C:\SCADA\Dakrosa1\Dakrosa1.mcp",
            {"id": 11, "name": r"U1\Power_nP"},
        )

        self.assertEqual(get_var_type.key_name, r"U1\Power_nP")
        self.assertEqual(get_var_type.count, 1)
        self.assertEqual(result, {"code": 9, "size": 8, "name": "Double"})

    def test_wincc_bin_discovery_honors_explicit_environment_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
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
        class GetValue:
            def __call__(self, key_ptr, count, update_ptr, error):
                update_ptr._obj.dmValue.vt = 4  # VT_R4
                update_ptr._obj.dmValue.fltVal = math.nan
                return 1

        fake_dm = type("FakeDM", (), {"DMGetValueW": GetValue()})()
        api = WinCCRuntimeAPI(dmclient=fake_dm, configure=False)

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
        api = WinCCRuntimeAPI(dmclient=fake_dm, configure=False)

        api.connect()
        api.disconnect()

        self.assertEqual(connect.app_name, "wincc-bridge")
        self.assertIsNotNone(connect.callback)
        self.assertTrue(disconnect.called)

    def test_ctypes_adapter_uses_distinct_canary_application_name(self):
        class Connect:
            def __call__(self, app_name, callback, user, error):
                self.app_name = app_name
                return 1

        class Disconnect:
            def __call__(self, error):
                return 1

        connect = Connect()
        fake_dm = type("FakeDM", (), {
            "DMConnectW": connect,
            "DMDisConnectW": Disconnect(),
        })()
        api = WinCCRuntimeAPI(
            dmclient=fake_dm,
            configure=False,
            application_name="wincc-bridge-canary",
        )

        api.connect()
        api.disconnect()

        self.assertEqual(connect.app_name, "wincc-bridge-canary")


if __name__ == "__main__":
    unittest.main()
