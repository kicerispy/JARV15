import ctypes
import pyautogui
from ctypes import wintypes

user32 = ctypes.windll.user32

class POINT(ctypes.Structure):
    _fields_ = [
        ("x", wintypes.LONG),
        ("y", wintypes.LONG),
    ]

class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]

class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", wintypes.DWORD),
    ]

mouse = pyautogui.position()

point = POINT(
    mouse.x,
    mouse.y,
)

monitor = user32.MonitorFromPoint(
    point,
    2,
)

info = MONITORINFO()
info.cbSize = ctypes.sizeof(MONITORINFO)

user32.GetMonitorInfoW(
    monitor,
    ctypes.byref(info),
)

print("mouse =", mouse)
print(
    "monitor_rect =",
    info.rcMonitor.left,
    info.rcMonitor.top,
    info.rcMonitor.right,
    info.rcMonitor.bottom,
)
print(
    "work_rect =",
    info.rcWork.left,
    info.rcWork.top,
    info.rcWork.right,
    info.rcWork.bottom,
)
print("flags =", info.dwFlags)
