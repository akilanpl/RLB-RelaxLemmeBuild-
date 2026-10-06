"""Internal Windows supervisor: contain descendants before launching project code."""

import os

# Run with the supplied project Python, including in frozen desktop releases.
# Only the supervisor owns the unnamed Job handle. Its death closes that handle,
# terminating descendants without PID discovery or permission-sensitive taskkill.
SUPERVISOR_CODE = r'''
import ctypes
import subprocess
import sys
import threading
from ctypes import wintypes

class BasicLimits(ctypes.Structure):
    _fields_ = [("ProcessTime", ctypes.c_int64), ("JobTime", ctypes.c_int64),
                ("Flags", wintypes.DWORD), ("MinWorkingSet", ctypes.c_size_t),
                ("MaxWorkingSet", ctypes.c_size_t), ("ActiveProcesses", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t), ("Priority", wintypes.DWORD),
                ("Scheduling", wintypes.DWORD)]

class IOCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in
                ("ReadOps", "WriteOps", "OtherOps", "ReadBytes", "WriteBytes", "OtherBytes")]

class ExtendedLimits(ctypes.Structure):
    _fields_ = [("Basic", BasicLimits), ("IO", IOCounters),
                ("ProcessMemory", ctypes.c_size_t), ("JobMemory", ctypes.c_size_t),
                ("PeakProcessMemory", ctypes.c_size_t), ("PeakJobMemory", ctypes.c_size_t)]

kernel = ctypes.WinDLL("kernel32", use_last_error=True)
kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
kernel.CreateJobObjectW.restype = wintypes.HANDLE
kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
kernel.SetInformationJobObject.restype = wintypes.BOOL
kernel.GetCurrentProcess.restype = wintypes.HANDLE
kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
kernel.AssignProcessToJobObject.restype = wintypes.BOOL
kernel.CloseHandle.argtypes = [wintypes.HANDLE]
kernel.CloseHandle.restype = wintypes.BOOL
kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel.OpenProcess.restype = wintypes.HANDLE
kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel.WaitForSingleObject.restype = wintypes.DWORD

job = kernel.CreateJobObjectW(None, None)
if not job:
    raise ctypes.WinError(ctypes.get_last_error())
limits = ExtendedLimits()
limits.Basic.Flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE; no breakaway.
if not kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
    error = ctypes.get_last_error()
    kernel.CloseHandle(job)
    raise ctypes.WinError(error)
if not kernel.AssignProcessToJobObject(job, kernel.GetCurrentProcess()):
    error = ctypes.get_last_error()
    kernel.CloseHandle(job)
    raise ctypes.WinError(error)  # Fail closed: project code has not started.

# Keep a handle to this specific runtime instance, rather than probing a reusable
# PID. Runtime crash/exit must not leave commands running independently.
parent = kernel.OpenProcess(0x00100000, False, int(sys.argv[1]))  # SYNCHRONIZE
if not parent:
    raise ctypes.WinError(ctypes.get_last_error())
def watch_parent():
    if kernel.WaitForSingleObject(parent, 0xFFFFFFFF) == 0:
        kernel.CloseHandle(job)
threading.Thread(target=watch_parent, daemon=True).start()

# CloseHandle on this job also kills this supervisor, so retain the handle until
# interpreter shutdown. The handle is non-inheritable and belongs to this process.
if sys.argv[2] == "shell":
    result = subprocess.call(sys.argv[3], shell=True)
else:
    result = subprocess.call(sys.argv[3:])
sys.exit(result)
'''


def supervised_argv(python: str, command: str | list[str]) -> list[str]:
    mode = "shell" if isinstance(command, str) else "exec"
    args = [command] if isinstance(command, str) else command
    return [python, "-c", SUPERVISOR_CODE, str(os.getpid()), mode, *args]
