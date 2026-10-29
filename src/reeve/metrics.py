"""RAM and CPU of the current process, via Win32 (no psutil)."""

from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes


class _MemCounters(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
        ("PrivateUsage", ctypes.c_size_t),   # PROCESS_MEMORY_COUNTERS_EX
    ]


_kernel32 = ctypes.windll.kernel32
_psapi = ctypes.windll.psapi
_kernel32.GetCurrentProcess.restype = wintypes.HANDLE
_kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
_psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(_MemCounters), wintypes.DWORD]


def _counters() -> _MemCounters:
    c = _MemCounters()
    c.cb = ctypes.sizeof(c)
    _psapi.GetProcessMemoryInfo(_kernel32.GetCurrentProcess(), ctypes.byref(c), c.cb)
    return c


def ram_mb() -> float:
    """Memory that belongs to Reeve alone (private bytes), in MB: close to what
    Task Manager shows. The working set is larger because it also counts the
    pages of system DLLs shared with other processes."""
    return _counters().PrivateUsage / 2**20


def working_set_mb() -> float:
    """Process working set, shared DLL pages included, in MB."""
    return _counters().WorkingSetSize / 2**20


def _cpu_seconds() -> float:
    ft = [wintypes.FILETIME() for _ in range(4)]
    _kernel32.GetProcessTimes(_kernel32.GetCurrentProcess(), *[ctypes.byref(f) for f in ft])
    kernel, user = ft[2], ft[3]
    return ((kernel.dwHighDateTime << 32 | kernel.dwLowDateTime) +
            (user.dwHighDateTime << 32 | user.dwLowDateTime)) / 1e7


class CpuMeter:
    """Process CPU between two calls: % of the machine and % of one core."""

    def __init__(self):
        self.cores = os.cpu_count() or 1
        self.t = time.perf_counter()
        self.c = _cpu_seconds()

    def sample(self) -> tuple[float, float]:
        t, c = time.perf_counter(), _cpu_seconds()
        dt = max(t - self.t, 1e-6)
        one_core = 100 * (c - self.c) / dt
        self.t, self.c = t, c
        return one_core / self.cores, one_core
