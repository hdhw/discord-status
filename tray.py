"""Notification-area (tray) icon with a right-click menu, using plain Win32.

The icon lives on its own thread with its own message loop. Menu callbacks run
on that thread, so anything touching Tk must be handed to the Tk thread.
"""

import ctypes
import ctypes.wintypes as wt
import threading

user32 = ctypes.WinDLL("user32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wt.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON),
                ("hCursor", wt.HANDLE), ("hbrBackground", wt.HBRUSH),
                ("lpszMenuName", wt.LPCWSTR), ("lpszClassName", wt.LPCWSTR)]


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wt.DWORD), ("Data2", wt.WORD), ("Data3", wt.WORD),
                ("Data4", ctypes.c_ubyte * 8)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("hWnd", wt.HWND), ("uID", wt.UINT),
                ("uFlags", wt.UINT), ("uCallbackMessage", wt.UINT), ("hIcon", wt.HICON),
                ("szTip", wt.WCHAR * 128), ("dwState", wt.DWORD), ("dwStateMask", wt.DWORD),
                ("szInfo", wt.WCHAR * 256), ("uVersion", wt.UINT),
                ("szInfoTitle", wt.WCHAR * 64), ("dwInfoFlags", wt.DWORD),
                ("guidItem", GUID), ("hBalloonIcon", wt.HICON)]


user32.DefWindowProcW.restype = LRESULT
user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.RegisterClassW.restype = wt.ATOM
user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
user32.CreateWindowExW.restype = wt.HWND
user32.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.HWND, wt.HMENU,
                                   wt.HINSTANCE, wt.LPVOID]
user32.DestroyWindow.argtypes = [wt.HWND]
user32.GetMessageW.restype = ctypes.c_int
user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
user32.TranslateMessage.argtypes = [ctypes.POINTER(wt.MSG)]
user32.DispatchMessageW.restype = LRESULT
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wt.MSG)]
user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.PostQuitMessage.argtypes = [ctypes.c_int]
user32.RegisterWindowMessageW.restype = wt.UINT
user32.RegisterWindowMessageW.argtypes = [wt.LPCWSTR]
user32.CreatePopupMenu.restype = wt.HMENU
user32.AppendMenuW.argtypes = [wt.HMENU, wt.UINT, ctypes.c_size_t, wt.LPCWSTR]
user32.SetMenuDefaultItem.argtypes = [wt.HMENU, wt.UINT, wt.UINT]
user32.TrackPopupMenu.restype = ctypes.c_int
user32.TrackPopupMenu.argtypes = [wt.HMENU, wt.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                  wt.HWND, ctypes.c_void_p]
user32.DestroyMenu.argtypes = [wt.HMENU]
user32.SetForegroundWindow.argtypes = [wt.HWND]
user32.GetCursorPos.argtypes = [ctypes.POINTER(wt.POINT)]
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.LoadImageW.restype = wt.HANDLE
user32.LoadImageW.argtypes = [wt.HINSTANCE, wt.LPCWSTR, wt.UINT, ctypes.c_int, ctypes.c_int,
                              wt.UINT]
user32.LoadIconW.restype = wt.HICON
user32.LoadIconW.argtypes = [wt.HINSTANCE, ctypes.c_void_p]
user32.DestroyIcon.argtypes = [wt.HICON]
shell32.Shell_NotifyIconW.argtypes = [wt.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
kernel32.GetModuleHandleW.restype = wt.HMODULE
kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]

NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP = 0x1, 0x2, 0x4
WM_DESTROY, WM_CLOSE, WM_NULL, WM_APP = 0x0002, 0x0010, 0x0000, 0x8000
WM_LBUTTONUP, WM_RBUTTONUP, WM_CONTEXTMENU = 0x0202, 0x0205, 0x007B
WM_TRAY = WM_APP + 1        # mouse events on the icon
WM_UPDATE_TIP = WM_APP + 2  # set_tooltip() from another thread
MF_STRING, MF_SEPARATOR, MF_CHECKED, MF_GRAYED = 0x0, 0x800, 0x8, 0x1
TPM_RIGHTBUTTON, TPM_RETURNCMD, TPM_NONOTIFY = 0x2, 0x100, 0x80
IMAGE_ICON, LR_LOADFROMFILE = 1, 0x10
SM_CXSMICON, SM_CYSMICON = 49, 50
IDI_APPLICATION = 32512


class TrayIcon:
    """`menu()` returns the items each time the menu opens:
    a list of (label, callback, checked, enabled) tuples, with None for a separator.
    `on_click` runs on a left click.
    """

    def __init__(self, icon_path, tooltip, menu, on_click=None):
        self.icon_path, self.tooltip = icon_path, tooltip
        self.menu, self.on_click = menu, on_click
        self.hwnd = None
        self.hicon = None
        self._taskbar_created = None
        self._ready = threading.Event()
        self._error = None
        self._thread = threading.Thread(target=self._run, name="tray", daemon=True)

    # -- any thread --
    def start(self):
        self._thread.start()
        self._ready.wait(5)
        if self._error:
            raise self._error
        if not self.hwnd:
            raise OSError("tray icon didn't start")

    def set_tooltip(self, text):
        self.tooltip = text
        if self.hwnd:
            user32.PostMessageW(self.hwnd, WM_UPDATE_TIP, 0, 0)

    def close(self):
        if self.hwnd:
            user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)
            self._thread.join(3)

    # -- tray thread --
    def _run(self):
        try:
            self._create()
        except Exception as e:
            self._error = e
            self._ready.set()
            return
        self._ready.set()
        msg = wt.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def _create(self):
        hinst = kernel32.GetModuleHandleW(None)
        self._proc = WNDPROC(self._wndproc)  # keep a reference: Windows calls it later
        cls = WNDCLASSW(lpfnWndProc=self._proc, hInstance=hinst,
                        lpszClassName="DiscordStatusTray")
        user32.RegisterClassW(ctypes.byref(cls))  # fails harmlessly if already registered
        # A regular (never shown) window rather than a message-only one, so it gets
        # the TaskbarCreated broadcast when Explorer restarts.
        self.hwnd = user32.CreateWindowExW(0, "DiscordStatusTray", "Discord Status", 0,
                                           0, 0, 0, 0, None, None, hinst, None)
        if not self.hwnd:
            raise ctypes.WinError(ctypes.get_last_error())
        self._taskbar_created = user32.RegisterWindowMessageW("TaskbarCreated")
        self.hicon = user32.LoadImageW(None, self.icon_path, IMAGE_ICON,
                                       user32.GetSystemMetrics(SM_CXSMICON),
                                       user32.GetSystemMetrics(SM_CYSMICON), LR_LOADFROMFILE)
        if not self.hicon:
            self.hicon = user32.LoadIconW(None, ctypes.c_void_p(IDI_APPLICATION))
        if not self._notify(NIM_ADD):
            raise OSError("couldn't add the tray icon")

    def _notify(self, action):
        data = NOTIFYICONDATAW()
        data.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        data.hWnd, data.uID = self.hwnd, 1
        data.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        data.uCallbackMessage = WM_TRAY
        data.hIcon = self.hicon
        data.szTip = self.tooltip[:127]
        return shell32.Shell_NotifyIconW(action, ctypes.byref(data))

    def _show_menu(self):
        items = self.menu()
        hmenu = user32.CreatePopupMenu()
        callbacks = {}
        for n, item in enumerate(items, start=1):
            if item is None:
                user32.AppendMenuW(hmenu, MF_SEPARATOR, 0, None)
                continue
            label, callback, checked, enabled = item
            flags = MF_STRING | (MF_CHECKED if checked else 0) | (0 if enabled else MF_GRAYED)
            user32.AppendMenuW(hmenu, flags, n, label)
            callbacks[n] = callback
        pos = wt.POINT()
        user32.GetCursorPos(ctypes.byref(pos))
        # Needed so the menu closes when you click somewhere else.
        user32.SetForegroundWindow(self.hwnd)
        chosen = user32.TrackPopupMenu(hmenu, TPM_RIGHTBUTTON | TPM_RETURNCMD | TPM_NONOTIFY,
                                       pos.x, pos.y, 0, self.hwnd, None)
        user32.PostMessageW(self.hwnd, WM_NULL, 0, 0)
        user32.DestroyMenu(hmenu)
        if callbacks.get(chosen):
            callbacks[chosen]()

    def _wndproc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == WM_TRAY:
                event = lparam & 0xFFFF
                if event in (WM_RBUTTONUP, WM_CONTEXTMENU):
                    self._show_menu()
                elif event == WM_LBUTTONUP and self.on_click:
                    user32.SetForegroundWindow(self.hwnd)  # lets the window it opens come to the front
                    self.on_click()
                return 0
            if msg == WM_UPDATE_TIP:
                self._notify(NIM_MODIFY)
                return 0
            if msg == self._taskbar_created:  # Explorer restarted: add the icon again
                self._notify(NIM_ADD)
                return 0
            if msg == WM_CLOSE:
                self._notify(NIM_DELETE)
                user32.DestroyWindow(hwnd)
                return 0
            if msg == WM_DESTROY:
                if self.hicon:
                    user32.DestroyIcon(self.hicon)
                user32.PostQuitMessage(0)
                return 0
        except Exception:
            pass  # never let an error escape into Windows
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)
