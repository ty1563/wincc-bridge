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
