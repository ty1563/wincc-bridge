import unittest

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


if __name__ == "__main__":
    unittest.main()
