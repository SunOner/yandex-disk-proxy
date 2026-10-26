import unittest

from downloads import CompletionEstimate


class Estimate(unittest.TestCase):
    def setUp(self):
        self.estimate = CompletionEstimate()

    def sample(self, at, count, size, active=True):
        self.estimate.sample({"count": count, "bytes": size}, active, now=at)

    def result(self, at, files=10, size=1000, active=True, ready=True):
        return self.estimate.result(files, size, active, ready, now=at)

    def test_warmup_and_confirmed_throughput(self):
        self.sample(0, 100, 10000)
        self.sample(15, 102, 10200)
        self.assertIsNone(self.result(15)["seconds"])
        self.sample(30, 106, 10600)
        self.assertEqual(self.result(30), {"status": "estimated", "seconds": 50})
        # Adding a folder changes the projection without changing the measured pace.
        self.assertEqual(self.result(30, files=100, size=10000)["seconds"], 500)

    def test_file_overhead_and_empty_files(self):
        self.sample(0, 0, 0)
        self.sample(30, 2, 10000)
        self.assertEqual(self.result(30, files=100, size=1000)["seconds"], 1500)
        self.assertEqual(self.result(30, files=100, size=0)["seconds"], 1500)
        empty = CompletionEstimate()
        empty.sample({"count": 0, "bytes": 0}, True, now=0)
        empty.sample({"count": 2, "bytes": 0}, True, now=30)
        self.assertEqual(empty.result(10, 0, True, True, now=30)["seconds"], 150)

    def test_idle_stall_pause_and_inventory_states_never_promise_completion(self):
        self.sample(0, 0, 0)
        self.sample(30, 2, 200)
        for at in range(60, 241, 30):
            self.sample(at, 2, 200)
        self.assertEqual(self.result(240)["status"], "waiting")
        self.assertIsNone(self.result(240)["seconds"])
        self.assertEqual(self.result(240, active=False)["status"], "paused")
        self.assertEqual(self.result(240, files=0, ready=False)["status"], "scanning")
        self.assertEqual(self.result(240, files=0), {"status": "complete", "seconds": 0})
        self.sample(245, 2, 200, active=False)
        self.sample(250, 2, 200)
        self.assertIsNone(self.result(250)["seconds"])

    def test_restart_sleep_or_history_switch_requires_a_new_window(self):
        self.sample(0, 10, 1000)
        self.sample(30, 12, 1200)
        self.assertEqual(self.result(30)["status"], "estimated")
        self.assertIsNone(self.result(61)["seconds"], "Do not reuse stale samples")
        self.sample(90, 50, 5000)
        self.assertIsNone(self.result(90)["seconds"], "Do not count downloads while asleep")
        self.sample(100, 0, 0)
        self.assertIsNone(
            self.result(100)["seconds"], "A different history invalidates the baseline"
        )
        self.assertIsNone(CompletionEstimate().result(10, 1000, True, True, now=100)["seconds"])

    def test_recent_window_is_bounded_and_old_rates_expire(self):
        for at in range(0, 3601, 5):
            self.sample(at, at // 5, at * 20)
        self.assertLessEqual(len(self.estimate.points), 122)
        self.assertEqual(self.result(3600, files=20, size=2000)["seconds"], 100)
        for at in range(3605, 4210, 5):
            self.sample(at, 720, 72000)
        self.assertIsNone(self.result(4205)["seconds"])
