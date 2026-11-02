"""winfiledlg — Windows 原生文件 / 文件夹选择对话框。

采用 Win32 经典 API（``comdlg32.GetOpenFileNameW`` / ``shell32.SHBrowseForFolderW``），
全部通过结构体传参，不做 COM 虚表调用，因此：

* 不需要 ``tkinter`` / PyQt / PowerShell 子进程，打包体积不增加；
* 初始目录直接由 ``lpstrInitialDir`` 指定（现代 ``IFileOpenDialog.SetFolder``
  在部分环境下会抛访问冲突，故不采用）；
* 只依赖 ``ctypes``，在任何 Windows 上行为一致。

两个公开函数：

* :func:`pick_file`   — 选一个文件（STEP / STL / OBJ），返回完整路径，取消返回 ``None``
* :func:`pick_folder` — 选一个文件夹，返回完整路径，取消返回 ``None``

对话框是模态的，会阻塞调用线程直到用户选择或取消 —— 调用方应放在可阻塞的
独立线程里（例如 HTTP 请求处理线程）。
"""
from __future__ import annotations

import ctypes
import os
import threading
import time
from ctypes import wintypes

__all__ = ["pick_file", "pick_folder", "pick_save", "is_available"]


_is_windows = os.name == "nt"

if _is_windows:
    comdlg32 = ctypes.WinDLL("comdlg32", use_last_error=True)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    ole32 = ctypes.WinDLL("ole32", use_last_error=True)
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


# --------------------------------------------------------------------------- #
# 常量
# --------------------------------------------------------------------------- #
OFN_OVERWRITEPROMPT = 0x00000002
OFN_EXPLORER = 0x00080000
OFN_PATHMUSTEXIST = 0x00000800
OFN_FILEMUSTEXIST = 0x00001000
OFN_NOCHANGEDIR = 0x00000008
OFN_HIDEREADONLY = 0x00000004
OFN_ALLOWMULTISELECT = 0x00000200

BIF_RETURNONLYFSDIRS = 0x00000001
BIF_NEWDIALOGSTYLE = 0x00000040
BIF_EDITBOX = 0x00000002
BIF_USENEWUI = BIF_NEWDIALOGSTYLE | BIF_EDITBOX

# BFFM_*: SHBrowseForFolder 回调消息
BFFM_INITIALIZED = 0x00000001
BFFM_SETSELECTIONW = 0x1043

MAX_PATH = 260

_EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
_BrowseCallback = ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HWND, wintypes.UINT,
                                     wintypes.LPARAM, wintypes.LPARAM)

# 最近一次使用的目录，作为下次对话框的初始位置
last_dir: str = os.path.expanduser("~")


def is_available() -> bool:
    """当前平台是否支持原生对话框。"""
    return _is_windows


# --------------------------------------------------------------------------- #
# 结构体
# --------------------------------------------------------------------------- #
class _OPENFILENAMEW(ctypes.Structure):
    _fields_ = [
        ("lStructSize", wintypes.DWORD),
        ("hwndOwner", wintypes.HWND),
        ("hInstance", wintypes.HINSTANCE),
        ("lpstrFilter", wintypes.LPCWSTR),
        ("lpstrCustomFilter", wintypes.LPWSTR),
        ("nMaxCustFilter", wintypes.DWORD),
        ("nFilterIndex", wintypes.DWORD),
        ("lpstrFile", wintypes.LPWSTR),
        ("nMaxFile", wintypes.DWORD),
        ("lpstrFileTitle", wintypes.LPWSTR),
        ("nMaxFileTitle", wintypes.DWORD),
        ("lpstrInitialDir", wintypes.LPCWSTR),
        ("lpstrTitle", wintypes.LPCWSTR),
        ("Flags", wintypes.DWORD),
        ("nFileOffset", wintypes.WORD),
        ("nFileExtension", wintypes.WORD),
        ("lpstrDefExt", wintypes.LPCWSTR),
        ("lCustData", wintypes.LPARAM),
        ("lpfnHook", ctypes.c_void_p),
        ("lpTemplateName", wintypes.LPCWSTR),
        ("pvReserved", ctypes.c_void_p),
        ("dwReserved", wintypes.DWORD),
        ("FlagsEx", wintypes.DWORD),
    ]


class _BROWSEINFOW(ctypes.Structure):
    _fields_ = [
        ("hwndOwner", wintypes.HWND),
        ("pszRoot", wintypes.LPCWSTR),
        ("pszTitle", wintypes.LPCWSTR),
        ("ulFlags", wintypes.UINT),
        ("lpfn", _BrowseCallback),
        ("lParam", wintypes.LPARAM),
        ("iImage", ctypes.c_int),
    ]


if _is_windows:
    comdlg32.GetOpenFileNameW.argtypes = [ctypes.POINTER(_OPENFILENAMEW)]
    comdlg32.GetOpenFileNameW.restype = wintypes.BOOL

    shell32.SHBrowseForFolderW.argtypes = [ctypes.POINTER(_BROWSEINFOW), wintypes.LPCWSTR]
    shell32.SHBrowseForFolderW.restype = ctypes.c_void_p

    shell32.SHGetPathFromIDListW.argtypes = [ctypes.c_void_p, wintypes.LPWSTR]
    shell32.SHGetPathFromIDListW.restype = wintypes.BOOL

    ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    ole32.CoInitializeEx.restype = ctypes.c_long

    ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    ole32.CoTaskMemFree.restype = None

    shell32.ILCreateFromPathW.argtypes = [wintypes.LPCWSTR]
    shell32.ILCreateFromPathW.restype = ctypes.c_void_p

    shell32.ILFree.argtypes = [ctypes.c_void_p]
    shell32.ILFree.restype = None


def _pidl_from_path(path: str):
    """把路径转成绝对 PIDL；失败返回 ``None``。

    用 ``ILCreateFromPathW``（经典 shell API）。注意：``SHParseDisplayName``
    虽然也能拿到 PIDL，但需要再走 COM 虚表取 ``IPersistFolder``，在部分
    环境下会直接导致进程崩溃，因此不采用。
    """
    if not path or not os.path.isdir(path):
        return None
    try:
        pidl = shell32.ILCreateFromPathW(os.path.abspath(path))
    except Exception:
        return None
    if not pidl:
        return None
    return ctypes.c_void_p(pidl)


class _ComApartment:
    """在**当前线程**初始化 COM（STA）。

    ``GetOpenFileNameW`` / ``SHBrowseForFolderW`` 都要求调用线程已初始化 COM，
    否则可能直接失败或表现为"对话框不出现"。
    """

    def __enter__(self):
        self._ok = False
        if _is_windows:
            hr = ole32.CoInitializeEx(None, 0x2)   # COINIT_APARTMENTTHREADED
            # 0=S_OK, 1=S_FALSE 都算成功；负值表示该线程已用其它模式初始化
            self._ok = hr >= 0
        return self

    def __exit__(self, *_exc):
        if self._ok:
            try:
                ole32.CoUninitialize()
            except Exception:
                pass
        return False


# --------------------------------------------------------------------------- #
# 置前处理（浏览器在前台时，把对话框拉到前面）
# --------------------------------------------------------------------------- #
def _force_foreground(hwnd: int) -> None:
    try:
        fg = user32.GetForegroundWindow()
        fg_thread = user32.GetWindowThreadProcessId(fg, None)
        cur_thread = kernel32.GetCurrentThreadId()
        attached = False
        if fg_thread and fg_thread != cur_thread:
            user32.AttachThreadInput(cur_thread, fg_thread, True)
            attached = True
        user32.ShowWindow(hwnd, 5)          # SW_SHOW
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        if attached:
            user32.AttachThreadInput(cur_thread, fg_thread, False)
    except Exception:
        pass


def _find_dialog_hwnd(pid: int):
    """在当前进程顶层窗口中找对话框（类名 #32770）。"""
    found = []

    def cb(hwnd, _lparam):
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, buf, 256)
        if buf.value == "#32770":
            wpid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
            if wpid.value == pid:
                found.append(hwnd)
        return True

    try:
        user32.EnumWindows(_EnumWindowsProc(cb), 0)
    except Exception:
        pass
    return found[0] if found else None


def _watch_foreground(stop: threading.Event, pid: int) -> None:
    """后台轮询，把对话框窗口拉到前台。"""
    deadline = time.time() + 30.0
    forced = 0
    while not stop.is_set() and time.time() < deadline and forced < 60:
        hwnd = _find_dialog_hwnd(pid)
        if hwnd:
            _force_foreground(hwnd)
            forced += 1
            time.sleep(0.15)
        else:
            time.sleep(0.08)


class _ForegroundGuard:
    """在模态对话框显示期间，持续把它置于前台。"""

    def __enter__(self):
        self._stop = threading.Event()
        self._th = threading.Thread(target=_watch_foreground,
                                    args=(self._stop, os.getpid()), daemon=True)
        self._th.start()
        return self

    def __exit__(self, *_exc):
        self._stop.set()
        return False


# --------------------------------------------------------------------------- #
# 文件选择
# --------------------------------------------------------------------------- #
def pick_file(
    title: str = "选择要打开的模型文件",
    filters: list | None = None,
    init_dir: str = "",
) -> str | None:
    """弹出原生「打开文件」对话框。

    ``filters`` 为 ``[(显示名, 通配符), ...]``，例如
    ``[("CAD 模型文件", "*.step;*.stp;*.stl;*.obj"), ("所有文件", "*.*")]``。
    取消返回 ``None``。
    """
    global last_dir
    if not _is_windows:
        raise RuntimeError("原生文件对话框仅支持 Windows")
    if filters is None:
        filters = [
            ("CAD 模型文件", "*.step;*.stp;*.stl;*.obj"),
            ("STEP 文件", "*.step;*.stp"),
            ("STL 文件", "*.stl"),
            ("OBJ 文件", "*.obj"),
            ("所有文件", "*.*"),
        ]

    # GetOpenFileNameW 的过滤器串：每项为 "显示名\0通配符\0"，末尾再多一个 \0
    parts: list[str] = []
    for name, spec in filters:
        parts.append(name)
        parts.append(spec)
    filter_str = "\0".join(parts) + "\0\0"

    buf = ctypes.create_unicode_buffer(MAX_PATH)
    buf.value = ""

    ofn = _OPENFILENAMEW()
    ofn.lStructSize = ctypes.sizeof(_OPENFILENAMEW)
    ofn.hwndOwner = None
    ofn.lpstrFilter = filter_str
    ofn.nFilterIndex = 1
    ofn.lpstrFile = ctypes.cast(buf, wintypes.LPWSTR)
    ofn.nMaxFile = MAX_PATH
    ofn.lpstrTitle = title
    ofn.lpstrDefExt = "step"
    ofn.Flags = (OFN_EXPLORER | OFN_FILEMUSTEXIST | OFN_PATHMUSTEXIST
                 | OFN_NOCHANGEDIR | OFN_HIDEREADONLY)

    start = init_dir or last_dir
    if start and os.path.isdir(start):
        ofn.lpstrInitialDir = os.path.abspath(start)

    with _ComApartment(), _ForegroundGuard():
        ok = comdlg32.GetOpenFileNameW(ctypes.byref(ofn))

    if not ok:
        return None
    path = buf.value
    if path:
        last_dir = os.path.dirname(path)
    return path or None


# --------------------------------------------------------------------------- #
# 保存对话框
# --------------------------------------------------------------------------- #
def pick_save(
    title: str = "保存为",
    default_name: str = "",
    filters: list | None = None,
    init_dir: str = "",
) -> str | None:
    """弹出原生「另存为」对话框；取消返回 ``None``。"""
    global last_dir
    if not _is_windows:
        raise RuntimeError("原生保存对话框仅支持 Windows")
    if filters is None:
        filters = [
            ("STEP 文件", "*.step"),
            ("STL 文件", "*.stl"),
            ("所有文件", "*.*"),
        ]

    parts: list[str] = []
    for name, spec in filters:
        parts.append(name)
        parts.append(spec)
    filter_str = "\0".join(parts) + "\0\0"

    buf = ctypes.create_unicode_buffer(MAX_PATH)
    buf.value = default_name or ""

    ofn = _OPENFILENAMEW()
    ofn.lStructSize = ctypes.sizeof(_OPENFILENAMEW)
    ofn.hwndOwner = None
    ofn.lpstrFilter = filter_str
    ofn.nFilterIndex = 1
    ofn.lpstrFile = ctypes.cast(buf, wintypes.LPWSTR)
    ofn.nMaxFile = MAX_PATH
    ofn.lpstrTitle = title
    ofn.lpstrDefExt = "step"
    ofn.Flags = (OFN_EXPLORER | OFN_OVERWRITEPROMPT | OFN_PATHMUSTEXIST
                 | OFN_NOCHANGEDIR | OFN_HIDEREADONLY)

    start = init_dir or last_dir
    if start and os.path.isdir(start):
        ofn.lpstrInitialDir = os.path.abspath(start)

    with _ComApartment(), _ForegroundGuard():
        ok = comdlg32.GetOpenFileNameW(ctypes.byref(ofn))

    if not ok:
        return None
    path = buf.value
    if path:
        last_dir = os.path.dirname(path)
    return path or None


# --------------------------------------------------------------------------- #
# 文件夹选择
# --------------------------------------------------------------------------- #
def pick_folder(
    title: str = "选择文件夹",
    init_dir: str = "",
) -> str | None:
    """弹出原生「浏览文件夹」对话框；取消返回 ``None``。

    对话框打开时会**自动定位**到 ``init_dir``（若存在），用户可自由上下级浏览。

    注意：``SHBrowseForFolderW`` 的窗口标题固定为「浏览文件夹」，
    ``title`` 通过 ``pszTitle`` 显示在对话框内的说明文字处。
    """
    global last_dir
    if not _is_windows:
        raise RuntimeError("原生文件夹对话框仅支持 Windows")

    with _ComApartment():
        start = os.path.abspath(init_dir or last_dir or os.path.expanduser("~"))
        if not os.path.isdir(start):
            start = os.path.abspath(os.path.expanduser("~"))

        # 预解析目标目录的 PIDL，供回调在对话框初始化后选中
        target_pidl = _pidl_from_path(start)

        def _callback(hwnd, msg, _lparam, _data):
            if msg == BFFM_INITIALIZED and target_pidl is not None:
                try:
                    # BFFM_SETSELECTIONW 需要一个"拥有"该 PIDL 的副本；
                    # 这里直接传原始 PIDL，shell 会自行复制
                    user32.SendMessageW(hwnd, BFFM_SETSELECTIONW, 0,
                                        target_pidl.value)
                except Exception:
                    pass
            return 0

        callback = _BrowseCallback(_callback)

        info = _BROWSEINFOW()
        info.hwndOwner = None
        info.pszRoot = None          # 显示完整目录树（不锁死在某一级）
        info.pszTitle = title
        info.ulFlags = BIF_RETURNONLYFSDIRS | BIF_NEWDIALOGSTYLE | BIF_EDITBOX
        info.lpfn = callback
        info.lParam = 0

        with _ForegroundGuard():
            pidl = shell32.SHBrowseForFolderW(ctypes.byref(info), title)
        if not pidl:
            return None

        try:
            path_buf = ctypes.create_unicode_buffer(MAX_PATH)
            if not shell32.SHGetPathFromIDListW(pidl, path_buf):
                return None
            path = path_buf.value
        finally:
            ole32.CoTaskMemFree(pidl)
            if target_pidl is not None:
                try:
                    shell32.ILFree(target_pidl)
                except Exception:
                    pass

    if path:
        last_dir = path
    return path or None
