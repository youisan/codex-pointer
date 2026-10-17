"""Local named events polled on the GUI thread; no network or Qt dependency."""
from __future__ import annotations

import ctypes

from .launcher import HIDE_EVENT_NAME, SHOW_EVENT_NAME


class ControlEvents:
    def __init__(self):
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateEventW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_wchar_p]
        self.kernel.CreateEventW.restype = ctypes.c_void_p
        self.kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        self.kernel.WaitForSingleObject.restype = ctypes.c_uint32
        self.kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        self.kernel.CloseHandle.restype = ctypes.c_int
        self.handles = []
        try:
            for name in (SHOW_EVENT_NAME, HIDE_EVENT_NAME):
                handle = self.kernel.CreateEventW(None, False, False, name)
                if not handle:
                    raise ctypes.WinError(ctypes.get_last_error())
                self.handles.append(handle)
        except OSError:
            self.close()
            raise

    def poll(self):
        values = []
        for handle in self.handles:
            state = self.kernel.WaitForSingleObject(handle, 0)
            if state == 0xFFFFFFFF:
                raise ctypes.WinError(ctypes.get_last_error())
            values.append(state == 0)
        return tuple(values)

    def close(self):
        for handle in self.handles:
            self.kernel.CloseHandle(handle)
        self.handles.clear()
