import os
import unittest

from bridge import runtime_canary


class RuntimeCallbackCanaryTests(unittest.TestCase):
    def setUp(self):
        runtime_canary._reset_for_tests()

    def tearDown(self):
        runtime_canary._reset_for_tests()

    def _cfg(self, station="Dakrosa2", mode="local", read_mode="raw", flag=None):
        station_cfg = {"name": station, "read_mode": read_mode}
        if flag is not None:
            station_cfg["runtime_callback_canary"] = flag
        return {
            "station": station_cfg,
            "winccbox": {
                "mode": mode,
                "python32": r"C:\Python311x86\python.exe",
                "reader": r"C:\bridge\box\oledb_reader.py",
            },
        }

    def test_canary_defaults_on_only_for_dakrosa2_local_raw(self):
        self.assertTrue(runtime_canary.enabled(self._cfg()))
        self.assertFalse(runtime_canary.enabled(self._cfg(station="Dakrosa1")))
        self.assertFalse(runtime_canary.enabled(self._cfg(mode="remote")))
        self.assertFalse(runtime_canary.enabled(self._cfg(read_mode="provider")))

    def test_explicit_false_is_a_kill_switch(self):
        self.assertFalse(runtime_canary.enabled(self._cfg(flag=False)))
        self.assertFalse(runtime_canary.enabled(self._cfg(flag="false")))
        self.assertTrue(runtime_canary.enabled(self._cfg(flag=True)))

    def test_command_uses_configured_python32_and_sibling_runtime_helper(self):
        command = runtime_canary.command(self._cfg())

        self.assertEqual(command[0], r"C:\Python311x86\python.exe")
        self.assertEqual(command[1], "-u")
        self.assertEqual(
            os.path.normpath(command[2]),
            os.path.normpath(r"C:\bridge\box\wincc_runtime.py"),
        )
        self.assertIn("--callback-canary", command)
        self.assertIn("--watch-stdin", command)
        self.assertEqual(command[command.index("--mode") + 1], "local")
        self.assertEqual(command[command.index("--read-mode") + 1], "raw")

    def test_status_accepts_structured_heartbeat_without_exposing_process_data(self):
        runtime_canary.record({
            "event": "heartbeat",
            "session": "pid-123",
            "callbacks": 12,
            "items": 48,
            "last_age_sec": 0.2,
            "tags": {"LV-KW": {"value": 2.41, "state": 0, "quality": 192}},
        })

        status = runtime_canary.status()

        self.assertEqual(status["event"], "heartbeat")
        self.assertEqual(status["callbacks"], 12)
        self.assertEqual(status["tags"]["LV-KW"]["quality"], 192)

    def test_start_is_singleton_and_never_launches_dakrosa1(self):
        class FakeThread:
            def __init__(self, target, args, daemon, name):
                self.target = target
                self.args = args
                self.daemon = daemon
                self.name = name
                self.started = False

            def start(self):
                self.started = True

            def is_alive(self):
                return self.started

            def join(self, timeout=None):
                self.started = False

        factory_calls = []

        def thread_factory(**kwargs):
            factory_calls.append(kwargs)
            return FakeThread(**kwargs)

        self.assertFalse(runtime_canary.start(
            self._cfg(station="Dakrosa1"), thread_factory=thread_factory))
        self.assertEqual(factory_calls, [])

        self.assertTrue(runtime_canary.start(
            self._cfg(), thread_factory=thread_factory))
        self.assertFalse(runtime_canary.start(
            self._cfg(), thread_factory=thread_factory))
        self.assertEqual(len(factory_calls), 1)

    def test_supervisor_records_config_error_instead_of_dying_silently(self):
        messages = []
        bad_cfg = {"station": {"name": "Dakrosa2", "read_mode": "raw"}}

        def log(message):
            messages.append(message)
            runtime_canary._stop_event.set()

        runtime_canary._supervise(
            bad_cfg,
            log,
            lambda *args, **kwargs: self.fail("Popen must not run"),
        )

        self.assertEqual(runtime_canary.status()["event"], "launch_error")
        self.assertTrue(any("launch_error" in message for message in messages))


if __name__ == "__main__":
    unittest.main()
