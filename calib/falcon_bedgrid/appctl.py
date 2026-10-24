"""Find / close / relaunch Falcon Design Space (Windows).

The app keeps the camera calibration in memory and writes it back to cameraConfig.txt when it
exits, so a new calibration has to be written while the app is *not* running.
"""
import ctypes
import csv
import io
import os
import subprocess
import time

EXE_NAME = "FalconDesignSpace.exe"
DEFAULT_EXE = r"C:\Program Files\Falcon Design Space\FalconDesignSpace.exe"
CREATE_NO_WINDOW = 0x08000000


def _run(args):
    return subprocess.run(args, capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)


def running_pids():
    out = _run(["tasklist", "/FO", "CSV", "/NH", "/FI", f"IMAGENAME eq {EXE_NAME}"]).stdout
    pids = []
    for row in csv.reader(io.StringIO(out)):
        if len(row) > 1 and row[0].lower() == EXE_NAME.lower():
            try:
                pids.append(int(row[1]))
            except ValueError:
                pass
    return pids


def _kernel32():
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.QueryFullProcessImageNameW.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                               ctypes.POINTER(wintypes.DWORD))
    k32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    k32.CloseHandle.argtypes = (wintypes.HANDLE,)
    k32.CloseHandle.restype = wintypes.BOOL
    return k32


def exe_path(pid):
    from ctypes import wintypes
    k32 = _kernel32()
    h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return None
    try:
        buf = ctypes.create_unicode_buffer(32768)
        n = wintypes.DWORD(len(buf))
        if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
            return buf.value
    finally:
        k32.CloseHandle(h)
    return None


def request_close(pid):
    """Polite close (WM_CLOSE), exactly like clicking the window's X - the app may ask to save."""
    _run(["taskkill", "/PID", str(pid)])


def wait_exit(pids, timeout_s, poll=None):
    end = time.time() + timeout_s
    while time.time() < end:
        alive = [p for p in pids if p in running_pids()]
        if not alive:
            return True
        if poll and poll() is False:
            return False
        time.sleep(0.5)
    return False


def launch(path):
    path = path if path and os.path.isfile(path) else DEFAULT_EXE
    if os.path.isfile(path):
        subprocess.Popen([path], cwd=os.path.dirname(path), close_fds=True,
                         creationflags=0x00000008)  # DETACHED_PROCESS
        return True
    return False
