"""Visibility event tests replace kernel32; never create native IPC objects."""

import ctypes
import unittest
from unittest.mock import Mock, call, patch

from codex_pointer.control_events import ControlEvents
from codex_pointer.launcher import HIDE_EVENT_NAME, SHOW_EVENT_NAME


class ControlEventTests(unittest.TestCase):
    def test_creates_unset_auto_reset_events_with_pointer_sized_handles(self):
        kernel = Mock()
        handles = [0x100000001, 0x100000002]
        kernel.CreateEventW.side_effect = handles
        with patch("codex_pointer.control_events.ctypes.WinDLL", return_value=kernel, create=True):
            events = ControlEvents()
        self.assertEqual(events.handles, handles)
        self.assertEqual(kernel.CreateEventW.call_args_list, [
            call(None, False, False, SHOW_EVENT_NAME),
            call(None, False, False, HIDE_EVENT_NAME),
        ])
        self.assertEqual(kernel.CreateEventW.restype, ctypes.c_void_p)
        self.assertEqual(kernel.WaitForSingleObject.argtypes, [ctypes.c_void_p, ctypes.c_uint32])
        self.assertEqual(kernel.CloseHandle.argtypes, [ctypes.c_void_p])
        kernel.WaitForSingleObject.assert_not_called()
        kernel.CloseHandle.assert_not_called()

    def test_poll_is_nonblocking_and_preserves_show_hide_order(self):
        kernel = Mock()
        kernel.CreateEventW.side_effect = [101, 102]
        # WAIT_OBJECT_0 signals a request; WAIT_TIMEOUT has no pending request.
        kernel.WaitForSingleObject.side_effect = [0, 258, 258, 0]
        with patch("codex_pointer.control_events.ctypes.WinDLL", return_value=kernel, create=True):
            events = ControlEvents()
        self.assertEqual(events.poll(), (True, False))
        self.assertEqual(events.poll(), (False, True))
        self.assertEqual(kernel.WaitForSingleObject.call_args_list, [
            call(101, 0), call(102, 0), call(101, 0), call(102, 0),
        ])

    def test_second_event_failure_closes_first_handle_and_propagates_error(self):
        kernel = Mock()
        kernel.CreateEventW.side_effect = [0x100000001, None]
        error = OSError("Cannot create hide event")
        with patch("codex_pointer.control_events.ctypes.WinDLL", return_value=kernel, create=True), \
                patch("codex_pointer.control_events.ctypes.get_last_error", return_value=5, create=True), \
                patch("codex_pointer.control_events.ctypes.WinError", return_value=error, create=True):
            with self.assertRaisesRegex(OSError, "Cannot create hide event"):
                ControlEvents()
        kernel.CloseHandle.assert_called_once_with(0x100000001)

    def test_first_event_failure_never_closes_invalid_handle(self):
        kernel = Mock()
        kernel.CreateEventW.return_value = None
        with patch("codex_pointer.control_events.ctypes.WinDLL", return_value=kernel, create=True), \
                patch("codex_pointer.control_events.ctypes.get_last_error", return_value=5, create=True), \
                patch("codex_pointer.control_events.ctypes.WinError", return_value=OSError("denied"), create=True):
            with self.assertRaises(OSError):
                ControlEvents()
        kernel.CloseHandle.assert_not_called()
        self.assertEqual(kernel.CreateEventW.call_count, 1)

    def test_close_releases_each_open_handle_once_and_is_idempotent(self):
        kernel = Mock()
        kernel.CreateEventW.side_effect = [101, 102]
        with patch("codex_pointer.control_events.ctypes.WinDLL", return_value=kernel, create=True):
            events = ControlEvents()
        events.close()
        events.close()
        self.assertEqual(kernel.CloseHandle.call_args_list, [call(101), call(102)])
        self.assertEqual(events.handles, [])

    def test_failed_wait_reports_native_error_instead_of_ignoring_it(self):
        kernel = Mock()
        kernel.CreateEventW.side_effect = [101, 102]
        kernel.WaitForSingleObject.return_value = 0xFFFFFFFF
        with patch("codex_pointer.control_events.ctypes.WinDLL", return_value=kernel, create=True), \
                patch("codex_pointer.control_events.ctypes.get_last_error", return_value=6, create=True), \
                patch("codex_pointer.control_events.ctypes.WinError", return_value=OSError("Invalid handle"), create=True):
            events = ControlEvents()
            with self.assertRaisesRegex(OSError, "Invalid handle"):
                events.poll()
        events.close()
        self.assertEqual(kernel.CloseHandle.call_args_list, [call(101), call(102)])


if __name__ == "__main__":
    unittest.main()
