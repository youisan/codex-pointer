"""Exercise the helper protocol with owned synthetic children, never Explorer."""
import sys
from threading import Event, Thread
import time
import unittest
from unittest.mock import patch

from codex_pointer.explorer_worker import ExplorerWorker, ExplorerWorkerError, ExplorerWorkerTimeout


FIXTURE = r'''
import json, os, sys, time
for line in sys.stdin:
    request = json.loads(line)
    if sys.argv[1] == "slow":
        time.sleep(20)
    if sys.argv[1] == "malformed":
        print("not json", flush=True)
        continue
    print(json.dumps({"id": request["id"], "result": {
        "path": request.get("path", "C:/测试/文件夹"), "kind": "folder", "pid": os.getpid(),
        "source": "file-drop" if "path" in request else "explorer-hit-test",
        "point": request.get("point"), "hwnd": request.get("hwnd"), "desktop": request.get("desktop")
    }}, ensure_ascii=False), flush=True)
'''


def command(mode="normal"):
    return [sys.executable, "-X", "utf8", "-u", "-c", FIXTURE, mode]


class ExplorerWorkerTests(unittest.TestCase):
    def test_path_requests_reuse_the_same_helper_as_window_requests(self):
        with ExplorerWorker("unused", command_factory=command) as worker:
            first = worker.query(123)
            second = worker.query_path("C:/测试/Folder [one] O'Brien $(throw 1).txt")
            third = worker.query_path("//server/Share name/资料")
        self.assertEqual(first["pid"], second["pid"])
        self.assertEqual(second["pid"], third["pid"])
        self.assertEqual(second["path"], "C:/测试/Folder [one] O'Brien $(throw 1).txt")
        self.assertEqual(third["path"], "//server/Share name/资料")
        self.assertEqual(second["source"], "file-drop")

    def test_invalid_path_values_never_spawn_a_helper(self):
        values = [None, True, "", "one.txt", r"C:relative.txt", "/root-relative", "https://example.org",
                  "C:/a\x00b", r"C:\file.txt:stream", r"\\.\PhysicalDrive0", r"\\?\GLOBALROOT\Device",
                  "//server", "//server/", "C:/bad*.txt", "C:/bad?.txt", "Registry::HKCU\\Software"]
        with ExplorerWorker("unused", command_factory=command) as worker, \
                patch("codex_pointer.explorer_worker.subprocess.Popen") as spawn:
            for path in values:
                with self.subTest(path=path), self.assertRaises(ValueError):
                    worker.query_path(path)
            spawn.assert_not_called()

    def test_path_lookup_timeout_is_bounded_and_next_query_can_restart(self):
        commands = iter([command("slow"), command()])
        with ExplorerWorker("unused", timeout=.4, command_factory=lambda: next(commands)) as worker:
            before = time.monotonic()
            with self.assertRaises(ExplorerWorkerTimeout):
                worker.query_path("//offline-server/share/资料")
            self.assertLess(time.monotonic() - before, 1.5)
            self.assertIsNone(worker._process)
            self.assertEqual(worker.query_path("C:/next")["path"], "C:/next")

    def test_long_request_cannot_block_forever_if_the_owned_child_never_reads_input(self):
        sleeper = [sys.executable, "-u", "-c", "import time; time.sleep(20)"]
        with ExplorerWorker("unused", timeout=.25, command_factory=lambda: sleeper) as worker:
            before = time.monotonic()
            with self.assertRaises(ExplorerWorkerTimeout):
                worker.query_path("C:/" + "文" * 20000)
            self.assertLess(time.monotonic() - before, 1.5)
            self.assertIsNone(worker._process)

    def test_path_request_can_be_cancelled_without_blocking_the_caller(self):
        worker = ExplorerWorker("unused", timeout=10, command_factory=lambda: command("slow"))
        errors = []
        def lookup():
            try:
                worker.query_path("//offline-server/share/one")
            except ExplorerWorkerError as error:
                errors.append(error)
        thread = Thread(target=lookup)
        thread.start()
        try:
            deadline = time.monotonic() + 2
            while worker._process is None and thread.is_alive() and time.monotonic() < deadline:
                time.sleep(.005)
            self.assertTrue(worker.cancel_active())
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())
            self.assertEqual(len(errors), 1)
        finally:
            worker.close()
            thread.join(timeout=2)

    def test_reuses_helper_but_does_not_cache_request_coordinates(self):
        with ExplorerWorker("unused", command_factory=command) as worker:
            first = worker.query(123, (-120, 450))
            second = worker.query(123, (600, 700), desktop=True)
        self.assertEqual(first["pid"], second["pid"])
        self.assertEqual(first["point"], [-120, 450])
        self.assertEqual(second["point"], [600, 700])
        self.assertTrue(second["desktop"])
        self.assertEqual(second["path"], "C:/测试/文件夹")

    def test_timeout_kills_owned_helper_and_next_request_restarts(self):
        commands = iter([command("slow"), command()])
        with ExplorerWorker("unused", timeout=0.5, command_factory=lambda: next(commands)) as worker:
            with self.assertRaises(ExplorerWorkerTimeout):
                worker.query(123)
            self.assertIsNone(worker._process)
            target = worker.query(456)
            self.assertEqual(target["hwnd"], 456)

    def test_malformed_response_is_not_reused_by_next_request(self):
        commands = iter([command("malformed"), command()])
        with ExplorerWorker("unused", command_factory=lambda: next(commands)) as worker:
            with self.assertRaises(ExplorerWorkerError):
                worker.query(123)
            self.assertEqual(worker.query(456)["hwnd"], 456)

    def test_close_terminates_only_child_and_closes_pipes(self):
        worker = ExplorerWorker("unused", command_factory=command)
        worker.query(123)
        process = worker._process
        worker.close()
        worker.close()
        self.assertIsNotNone(process.poll())
        self.assertTrue(process.stdin.closed)
        self.assertTrue(process.stdout.closed)
        self.assertIsNone(worker._process)

    def test_cancel_interrupts_slow_lookup_without_waiting_request_lock(self):
        worker = ExplorerWorker("unused", timeout=10, command_factory=lambda: command("slow"))
        errors = []

        def lookup():
            try:
                worker.query(123)
            except ExplorerWorkerError as error:
                errors.append(error)

        thread = Thread(target=lookup)
        thread.start()
        try:
            deadline = time.monotonic() + 3
            while worker._process is None and thread.is_alive() and time.monotonic() < deadline:
                time.sleep(0.005)
            self.assertIsNotNone(worker._process)
            before = time.monotonic()
            self.assertTrue(worker.cancel_active())
            self.assertLess(time.monotonic() - before, 0.25)
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())
            self.assertEqual(len(errors), 1)
        finally:
            worker.close()
            thread.join(timeout=2)

    def test_cancelling_when_idle_preserves_the_warmed_helper(self):
        with ExplorerWorker("unused", command_factory=command) as worker:
            first = worker.query(123)
            process = worker._process
            for _ in range(3):
                self.assertFalse(worker.cancel_active())
            self.assertIsNone(process.poll())
            second = worker.query(456)
        self.assertEqual(first["pid"], second["pid"])

    def test_active_cancel_during_startup_stops_the_newly_created_child(self):
        starting, release = Event(), Event()
        errors = []

        def delayed_command():
            starting.set()
            release.wait(timeout=2)
            return command()

        worker = ExplorerWorker("unused", command_factory=delayed_command)

        def lookup():
            try:
                worker.query(123)
            except ExplorerWorkerError as error:
                errors.append(error)

        thread = Thread(target=lookup)
        thread.start()
        try:
            self.assertTrue(starting.wait(timeout=2))
            self.assertTrue(worker.cancel_active())
            release.set()
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())
            self.assertEqual(len(errors), 1)
            self.assertIn("cancelled", str(errors[0]))
            self.assertIsNone(worker._process)
        finally:
            release.set()
            worker.close()
            thread.join(timeout=2)

    def test_invalid_native_values_never_spawn_a_helper(self):
        with ExplorerWorker("unused", command_factory=command) as worker, \
                patch("codex_pointer.explorer_worker.subprocess.Popen") as spawn:
            for hwnd, point in [(0, None), (True, None), (123, (1, 2 ** 31)), (123, (True, 5))]:
                with self.assertRaises(ValueError):
                    worker.query(hwnd, point)
            spawn.assert_not_called()

    def test_waiting_request_has_a_bound_and_does_not_interrupt_another_owner(self):
        worker = ExplorerWorker("unused", timeout=0.05, command_factory=command)
        worker._lock.acquire()
        try:
            with patch.object(worker, "_start") as start, patch.object(worker, "cancel") as cancel:
                with self.assertRaises(ExplorerWorkerTimeout):
                    worker.query(123)
            start.assert_not_called()
            cancel.assert_not_called()
        finally:
            worker._lock.release()
            worker.close()

    def test_simultaneous_calls_are_serial_and_match_their_own_responses(self):
        results = []
        with ExplorerWorker("unused", command_factory=command) as worker:
            threads = [Thread(target=lambda n=n: results.append(worker.query(n, (n, n)))) for n in range(1, 7)]
            for thread in threads: thread.start()
            for thread in threads: thread.join(timeout=3)
            self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(sorted(result["hwnd"] for result in results), list(range(1, 7)))
        self.assertTrue(all(result["point"] == [result["hwnd"]] * 2 for result in results))

    @unittest.skipUnless(sys.platform == "win32", "PowerShell wrapper requires Windows")
    def test_real_powershell_wrapper_with_owned_metadata_fixture(self):
        from codex_pointer import windows
        # Load the production wrapper and assemblies, replacing only its target
        # lookup with a pure fixture. Never inspect an open Explorer window.
        fixture = r'''
param([long]$TargetHwnd, [int]$X = 0, [int]$Y = 0,
      [switch]$HasPoint, [switch]$Desktop)
return @{path='C:/测试/文件夹';kind='folder';hwnd=$TargetHwnd;
         point=@($X,$Y);hasPoint=[bool]$HasPoint;desktop=[bool]$Desktop;pid=$PID}
'''
        script = windows._EXPLORER_WORKER_SCRIPT.replace(windows._EXPLORER_SCRIPT, fixture)
        with ExplorerWorker(script) as worker:
            first = worker.query(123, (-40, 50))
            second = worker.query(456, desktop=True)
        self.assertEqual(first["path"], "C:/测试/文件夹")
        self.assertEqual(first["point"], [-40, 50])
        self.assertTrue(first["hasPoint"])
        self.assertFalse(second["hasPoint"])
        self.assertTrue(second["desktop"])
        self.assertEqual(second["hwnd"], 456)
        self.assertEqual(first["pid"], second["pid"])


if __name__ == "__main__":
    unittest.main()
