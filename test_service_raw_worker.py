import unittest
from unittest import mock

from bridge import service


class FakeThread:
    instances = []

    def __init__(self, target, args, daemon, name):
        self.target = target
        self.args = args
        self.daemon = daemon
        self.name = name
        self.started = False
        self.alive = False
        self.__class__.instances.append(self)

    def start(self):
        self.started = True
        self.alive = True

    def is_alive(self):
        return self.alive


class RawShipWorkerTests(unittest.TestCase):
    def setUp(self):
        service._raw_thread = None
        FakeThread.instances.clear()

    def tearDown(self):
        service._raw_thread = None

    def test_start_raw_ship_schedules_daemon_without_running_job_inline(self):
        cfg = {"station": {"name": "Dakrosa2"}}

        started = service.start_raw_ship(cfg, thread_factory=FakeThread)

        self.assertTrue(started)
        thread = FakeThread.instances[0]
        self.assertTrue(thread.started)
        self.assertTrue(thread.daemon)
        self.assertEqual(thread.name, "wincc-raw-ship")
        self.assertEqual(thread.args, (cfg,))
        self.assertTrue(service.raw_ship_active())

    def test_start_raw_ship_prevents_overlapping_raw_jobs(self):
        cfg = {"station": {"name": "Dakrosa2"}}
        service.start_raw_ship(cfg, thread_factory=FakeThread)

        second = service.start_raw_ship(cfg, thread_factory=FakeThread)

        self.assertFalse(second)
        self.assertEqual(len(FakeThread.instances), 1)

    def test_start_raw_ship_allows_next_job_after_previous_finishes(self):
        cfg = {"station": {"name": "Dakrosa2"}}
        service.start_raw_ship(cfg, thread_factory=FakeThread)
        FakeThread.instances[0].alive = False

        second = service.start_raw_ship(cfg, thread_factory=FakeThread)

        self.assertTrue(second)
        self.assertEqual(len(FakeThread.instances), 2)

    def test_raw_ship_active_is_false_without_worker(self):
        self.assertFalse(service.raw_ship_active())

    def test_dakrosa2_runtime_snapshot_matches_dashboard_refresh_cadence(self):
        cfg = {
            "station": {"name": "Dakrosa2", "read_mode": "raw"},
            "intervals": {"snapshot_sec": 300},
        }

        self.assertEqual(service.effective_snap_iv(cfg, runtime_active=True), 10)
        self.assertEqual(service.effective_snap_iv(cfg, runtime_active=False), 30)

    def test_dakrosa1_keeps_conservative_snapshot_ceiling(self):
        cfg = {
            "station": {"name": "Dakrosa1"},
            "intervals": {"snapshot_sec": 300},
        }

        self.assertEqual(service.effective_snap_iv(cfg), 30)

    def test_one_snapshot_returns_runtime_mode_for_adaptive_cadence(self):
        cfg = {"station": {"name": "Dakrosa2"}}
        snap = {"read_mode": "runtime", "tags": {"u1_P": {"last": 790.0}}}

        with mock.patch.object(service.collect, "collect", return_value=snap), \
                mock.patch.object(service.collect, "local_version", return_value="1.5.11"), \
                mock.patch.object(service.poster, "post", return_value=(200, "ok")), \
                mock.patch.object(service.poster, "post_extra", return_value=(200, "ok")):
            payload = service.one_snapshot(cfg)

        self.assertEqual(payload["station"], "Dakrosa2")
        self.assertEqual(payload["read_mode"], "runtime")
        self.assertEqual(payload["version"], "1.5.11")

    def test_one_snapshot_attaches_callback_canary_status_when_available(self):
        cfg = {"station": {"name": "Dakrosa2"}}
        snap = {"read_mode": "runtime", "tags": {"u1_P": {"last": 790.0}}}
        canary = {"event": "heartbeat", "callbacks": 7, "last_age_sec": 0.1}

        with mock.patch.object(service.collect, "collect", return_value=snap), \
                mock.patch.object(service.collect, "local_version", return_value="1.5.12"), \
                mock.patch.object(service.runtime_canary, "status", return_value=canary), \
                mock.patch.object(service.poster, "post", return_value=(200, "ok")), \
                mock.patch.object(service.poster, "post_extra", return_value=(200, "ok")):
            payload = service.one_snapshot(cfg)

        self.assertEqual(payload["runtime_canary"], canary)

    def test_due_maintenance_checks_ota_before_starting_raw_job(self):
        order = []

        result = service.run_due_maintenance(
            {"station": {"name": "Dakrosa1"}},
            ota_due=True,
            raw_due=True,
            check_update=lambda cfg, log: order.append("ota") or False,
            raw_starter=lambda cfg: order.append("raw") or True,
            active_check=lambda: False,
            log_fn=lambda message: None,
        )

        self.assertEqual(order, ["ota", "raw"])
        self.assertTrue(result["ota_checked"])
        self.assertTrue(result["raw_started"])
        self.assertFalse(result["updated"])

    def test_successful_ota_does_not_start_an_obsolete_raw_job(self):
        raw_starter = mock.Mock()

        result = service.run_due_maintenance(
            {},
            ota_due=True,
            raw_due=True,
            check_update=lambda cfg, log: True,
            raw_starter=raw_starter,
            active_check=lambda: False,
            log_fn=lambda message: None,
        )

        self.assertTrue(result["updated"])
        raw_starter.assert_not_called()

    def test_startup_station_sync_is_best_effort(self):
        messages = []

        self.assertTrue(service.sync_station_files_on_start(
            {"station": {"name": "Dakrosa1"}},
            sync=lambda cfg: True,
            log_fn=messages.append,
        ))
        self.assertIn("Dakrosa1", messages[0])

        self.assertFalse(service.sync_station_files_on_start(
            {},
            sync=lambda cfg: (_ for _ in ()).throw(RuntimeError("offline")),
            log_fn=messages.append,
        ))
        self.assertIn("offline", messages[-1])


if __name__ == "__main__":
    unittest.main()
