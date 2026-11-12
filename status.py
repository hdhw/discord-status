"""Discord Rich Presence that follows whatever app is in the foreground.

Windows only. No third-party dependencies: talks to Discord's local IPC pipe
directly and reads the foreground window through ctypes. Rules live in
config.json (created from config.example.json on first run), which is
reloaded automatically when it changes.

Usage:
    python status.py              run (use pythonw.exe to run without a console)
    python status.py --dry-run    print what would be shown, don't touch Discord
    python status.py --autostart  start quietly (no setup or control windows)

Built as DiscordStatus.exe (see build.bat), settings live in
%APPDATA%\\DiscordStatus instead of next to the script.
"""

import ctypes
import ctypes.wintypes as wt
import json
import os
import re
import struct
import sys
import time
import uuid

FROZEN = getattr(sys, "frozen", False)  # running as DiscordStatus.exe
if FROZEN:
    HERE = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "DiscordStatus")
    BUNDLE = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    os.makedirs(HERE, exist_ok=True)
else:
    HERE = BUNDLE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")
EXAMPLE_CONFIG_PATH = os.path.join(BUNDLE, "config.example.json")
ICON_PATH = os.path.join(BUNDLE, "icon.ico")
PLACEHOLDER_ID = "PASTE_YOUR_APPLICATION_ID_HERE"
LOG_PATH = os.path.join(HERE, "status.log")

# --------------------------------------------------------------------------
# Windows: foreground window, owning process, idle time
# --------------------------------------------------------------------------

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

user32.GetForegroundWindow.restype = wt.HWND
user32.GetWindowTextLengthW.argtypes = [wt.HWND]
user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
kernel32.OpenProcess.restype = wt.HANDLE
kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
kernel32.QueryFullProcessImageNameW.argtypes = [
    wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
kernel32.CloseHandle.argtypes = [wt.HANDLE]

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.UINT), ("dwTime", wt.DWORD)]


def window_title(hwnd):
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def exe_for_pid(pid):
    exe = ""
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if handle:
        try:
            size = wt.DWORD(1024)
            path = ctypes.create_unicode_buffer(size.value)
            if kernel32.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(size)):
                exe = os.path.basename(path.value)
        finally:
            kernel32.CloseHandle(handle)
    return exe


def foreground():
    """Return (exe_name, window_title, pid) of the focused window."""
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return "", "", 0
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return exe_for_pid(pid.value), window_title(hwnd), pid.value


EnumWindowsProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
user32.EnumWindows.argtypes = [EnumWindowsProc, wt.LPARAM]
user32.IsWindowVisible.argtypes = [wt.HWND]
DWMWA_CLOAKED = 14


def list_windows():
    """Return [(exe_name, title)] for the visible app windows, for the rule editor."""
    found = []

    def visit(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        if user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOOLWINDOW:
            return True
        cloaked = wt.DWORD()  # hidden UWP windows still report as visible
        try:
            ctypes.windll.dwmapi.DwmGetWindowAttribute(
                hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
        except (AttributeError, OSError):
            pass
        if cloaked.value:
            return True
        title = window_title(hwnd)
        pid = _window_pid(hwnd)
        if title and pid != os.getpid():
            exe = exe_for_pid(pid)
            if exe and (exe, title) not in found:
                found.append((exe, title))
        return True

    user32.EnumWindows(EnumWindowsProc(visit), 0)
    return found


def idle_seconds():
    info = LASTINPUTINFO(cbSize=ctypes.sizeof(LASTINPUTINFO))
    if not user32.GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    # GetTickCount wraps every ~49 days; mask keeps the subtraction sane.
    return ((kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF) / 1000.0


# --------------------------------------------------------------------------
# Discord IPC (named pipe, frames are: int32 op, int32 length, JSON body)
# --------------------------------------------------------------------------

OP_HANDSHAKE, OP_FRAME, OP_CLOSE = 0, 1, 2


class DiscordError(Exception):
    pass


class DiscordIPC:
    def __init__(self, client_id):
        self.client_id = str(client_id)
        self.pipe = None

    def connect(self):
        last = None
        for i in range(10):
            try:
                self.pipe = open(r"\\.\pipe\discord-ipc-%d" % i, "r+b", buffering=0)
                break
            except OSError as e:
                last = e
        else:
            raise DiscordError("Discord isn't running (no IPC pipe): %s" % last)
        self._send(OP_HANDSHAKE, {"v": 1, "client_id": self.client_id})
        op, data = self._recv()
        if op == OP_CLOSE or data.get("evt") != "READY":
            self.close()
            raise DiscordError("handshake rejected: %s" % data)

    def set_activity(self, activity):
        self._send(OP_FRAME, {
            "cmd": "SET_ACTIVITY",
            "args": {"pid": os.getpid(), "activity": activity},
            "nonce": str(uuid.uuid4()),
        })
        op, data = self._recv()
        if op == OP_CLOSE:
            raise DiscordError("Discord closed the connection: %s" % data)
        if data.get("evt") == "ERROR":
            # Bad activity payload; the connection itself is still fine.
            raise ValueError("Discord rejected activity: %s" % data.get("data"))

    def close(self):
        if self.pipe:
            try:
                self.pipe.close()
            except OSError:
                pass
        self.pipe = None

    def _send(self, op, payload):
        body = json.dumps(payload).encode("utf-8")
        self.pipe.write(struct.pack("<ii", op, len(body)) + body)

    def _read_exact(self, n):
        out = b""
        while len(out) < n:
            chunk = self.pipe.read(n - len(out))
            if not chunk:
                raise DiscordError("pipe closed")
            out += chunk
        return out

    def _recv(self):
        op, length = struct.unpack("<ii", self._read_exact(8))
        return op, json.loads(self._read_exact(length).decode("utf-8"))


# --------------------------------------------------------------------------
# Rules
# --------------------------------------------------------------------------

class _Blank(dict):
    def __missing__(self, key):
        return ""


def read_config():
    """config.json as plain data (no compiled rules)."""
    # utf-8-sig: accept files saved with a BOM (some Windows editors add one).
    with open(CONFIG_PATH, encoding="utf-8-sig") as f:
        return json.load(f)


def compile_rules(rules):
    """Copy the rules and attach the precompiled matchers match() needs."""
    out = []
    for rule in rules:
        rule = dict(rule)
        rule["_procs"] = {p.lower() for p in rule.get("process", [])}
        rule["_re"] = re.compile(rule["title"], re.I) if rule.get("title") else None
        out.append(rule)
    return out


def load_config():
    cfg = read_config()
    cfg["rules"] = compile_rules(cfg.get("rules", []))
    return cfg


def format_config(cfg):
    """JSON with one line per setting and per rule, so it stays hand-editable."""
    items = ["  %s: %s" % (json.dumps(k), json.dumps(v, ensure_ascii=False))
             for k, v in cfg.items() if k != "rules"]
    rules = cfg.get("rules", [])
    if rules:
        items.append('  "rules": [\n%s\n  ]' % ",\n".join(
            "    " + json.dumps(r, ensure_ascii=False) for r in rules))
    else:
        items.append('  "rules": []')
    return "{\n" + ",\n".join(items) + "\n}\n"


def write_config(cfg):
    """Save config.json atomically; the previous version goes to config.backup.json."""
    text = format_config(cfg)
    json.loads(text)  # never write something we can't read back
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    if os.path.exists(CONFIG_PATH):
        import shutil
        shutil.copyfile(CONFIG_PATH, os.path.join(HERE, "config.backup.json"))
    for _ in range(20):  # the running copy may be reading it this instant
        try:
            os.replace(tmp, CONFIG_PATH)
            return
        except PermissionError:
            time.sleep(0.05)
    os.replace(tmp, CONFIG_PATH)


def match(cfg, exe, title):
    """Return (rule_key, rule, template_vars) for the first matching rule."""
    for i, rule in enumerate(cfg.get("rules", [])):
        if rule["_procs"] and exe.lower() not in rule["_procs"]:
            continue
        groups = {}
        if rule["_re"]:
            m = rule["_re"].search(title)
            if not m:
                continue
            groups = {k: (v or "").strip() for k, v in m.groupdict().items()}
        return "rule%d" % i, rule, groups
    return None, None, {}


TEXT_FIELDS = ("details", "state", "large_text", "small_text")
IMAGE_FIELDS = ("large_image", "small_image")


STATUS_DISPLAY = {"name": 0, "state": 1, "details": 2}


def build_activity(rule, groups, started, status_display=None):
    """Turn a rule into a Discord activity dict (None means clear it)."""
    if not rule:
        return None
    act = {}
    text = {}
    for field in TEXT_FIELDS:
        if rule.get(field):
            value = rule[field].format_map(_Blank(groups)).strip()
            if len(value) >= 2:  # Discord rejects 1-char strings
                text[field] = value[:128]
    for field in ("details", "state"):
        if field in text:
            act[field] = text[field]
    assets = {}
    for field in IMAGE_FIELDS:
        if rule.get(field):
            assets[field] = rule[field]
    for field in ("large_text", "small_text"):
        if field in text and field.replace("text", "image") in assets:
            assets[field] = text[field]
    if assets:
        act["assets"] = assets
    if rule.get("type") in (0, 2, 3, 5):
        act["type"] = rule["type"]
    # Which text the member list shows next to your name: the app name,
    # "state" or "details". Per-rule setting wins over the global one.
    display = STATUS_DISPLAY.get(rule.get("status_display", status_display))
    if display:
        act["status_display_type"] = display
    if rule.get("show_elapsed", True):
        act["timestamps"] = {"start": int(started)}
    if rule.get("buttons"):
        act["buttons"] = rule["buttons"][:2]
    return act or None


# --------------------------------------------------------------------------
# Main loop
# --------------------------------------------------------------------------

def log(msg):
    line = time.strftime("%Y-%m-%d %H:%M:%S ") + msg
    if sys.stdout is not None and not FROZEN:
        print(line, flush=True)
    else:  # pythonw or the exe: no console, write to a small log instead
        try:
            if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > 256_000:
                os.replace(LOG_PATH, LOG_PATH + ".old")
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass


ERROR_ALREADY_EXISTS = 183
kernel32.CreateMutexW.restype = wt.HANDLE
kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.LPCWSTR]


def claim_single_instance():
    """Return a mutex handle, or None if another copy is already running."""
    handle = kernel32.CreateMutexW(None, False, "Local\\DiscordStatusPresence")
    if handle and ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        # Let go of it, or this copy (e.g. an open control panel) would keep the
        # mutex alive after the real one stops and block the next start.
        kernel32.CloseHandle(handle)
        return None
    return handle or None


# A named event lets a second launch (the control window) stop the running copy.
WAIT_OBJECT_0 = 0
kernel32.CreateEventW.restype = wt.HANDLE
kernel32.CreateEventW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.BOOL, wt.LPCWSTR]
kernel32.SetEvent.argtypes = [wt.HANDLE]
kernel32.ResetEvent.argtypes = [wt.HANDLE]
kernel32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
_stop_event = kernel32.CreateEventW(None, True, False, "Local\\DiscordStatusPresenceStop")


def request_stop():
    """Ask the running copy to exit (called from the control window)."""
    if _stop_event:
        kernel32.SetEvent(_stop_event)


def wait_for_stop(seconds):
    """Sleep up to `seconds`; return True if a stop was requested."""
    if not _stop_event:
        time.sleep(seconds)
        return False
    return kernel32.WaitForSingleObject(_stop_event, int(seconds * 1000)) == WAIT_OBJECT_0


# --------------------------------------------------------------------------
# Setup helpers: config file, Application ID, start with Windows
# --------------------------------------------------------------------------

def ensure_config():
    if not os.path.exists(CONFIG_PATH):
        import shutil
        shutil.copyfile(EXAMPLE_CONFIG_PATH, CONFIG_PATH)
        log("created config.json from config.example.json")


def current_client_id():
    try:
        value = str(load_config().get("client_id", "")).strip()
    except (OSError, ValueError, re.error):
        return ""
    return "" if value == PLACEHOLDER_ID else value


def save_client_id(client_id):
    """Write client_id into config.json, keeping the rest of the file as-is."""
    with open(CONFIG_PATH, encoding="utf-8-sig") as f:
        text = f.read()
    new, count = re.subn(r'("client_id"\s*:\s*)"[^"]*"',
                         lambda m: m.group(1) + json.dumps(client_id), text, count=1)
    if not count:
        data = json.loads(text)
        data["client_id"] = client_id
        new = json.dumps(data, indent=2)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        f.write(new)


def startup_shortcut():
    appdata = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(appdata, "Microsoft", "Windows", "Start Menu", "Programs",
                        "Startup", "Discord Status.lnk")


def autostart_enabled():
    return os.path.exists(startup_shortcut())


def set_autostart(enabled):
    path = startup_shortcut()
    if not enabled:
        if os.path.exists(path):
            os.remove(path)
        return
    if FROZEN:
        target, args = sys.executable, "--autostart"
    else:
        target = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        args = '"%s" --autostart' % os.path.abspath(__file__)
    import subprocess
    env = dict(os.environ, DS_LNK=path, DS_TARGET=target, DS_ARGS=args,
               DS_DIR=os.path.dirname(target if FROZEN else os.path.abspath(__file__)))
    script = ("$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:DS_LNK);"
              "$s.TargetPath = $env:DS_TARGET; $s.Arguments = $env:DS_ARGS;"
              "$s.WorkingDirectory = $env:DS_DIR; $s.Save()")
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                   env=env, check=True, creationflags=0x08000000)  # CREATE_NO_WINDOW


# --------------------------------------------------------------------------
# Bottom-right popup when the status changes
# --------------------------------------------------------------------------

GWL_EXSTYLE = -20
WS_EX_TOPMOST = 0x00000008
WS_EX_TRANSPARENT = 0x00000020  # clicks pass through
WS_EX_TOOLWINDOW = 0x00000080   # no taskbar button / alt-tab entry
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000   # never takes focus
SPI_GETWORKAREA = 0x0030

user32.SetForegroundWindow.argtypes = [wt.HWND]


def _window_pid(hwnd):
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


user32.GetWindowLongW.argtypes = [wt.HWND, ctypes.c_int]
user32.SetWindowLongW.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_long]
user32.SystemParametersInfoW.argtypes = [wt.UINT, wt.UINT, ctypes.c_void_p, wt.UINT]


class Toast:
    """A small click-through popup that never steals focus.

    Tk must live on the main thread, so the presence loop runs on a worker
    thread and hands messages over through a queue.
    """

    # Deliberately low-key: one dim line, translucent, short and soft fades.
    BG, BORDER, ACCENT, FG = "#1e1f22", "#2b2d31", "#4e5058", "#b5bac1"
    MAX_ALPHA, FADE_IN_MS, FADE_OUT_MS, MAX_CHARS = 0.85, 250, 600, 70

    def __init__(self):
        import queue
        import tkinter as tk
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # crisp text on scaled displays
        except (AttributeError, OSError):
            pass
        self.tk, self.queue = tk, queue.Queue()
        # Tk's hidden root window grabs focus once while it's being created;
        # hand focus straight back to whatever had it.
        previous = user32.GetForegroundWindow()
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.update()
        now = user32.GetForegroundWindow()
        if previous and now != previous and _window_pid(now) == os.getpid():
            user32.SetForegroundWindow(previous)
        self.scale = self.root.winfo_fpixels("1i") / 96.0
        self.win = None
        self.jobs = []

    # -- called from the worker thread --
    def show(self, title, body, seconds, position="bottom-right"):
        self.queue.put(("show", title, body, seconds, position))

    def stop(self):
        self.queue.put(("stop",))

    # -- main thread --
    def run(self):
        self.root.after(150, self._poll)
        self.root.mainloop()

    def _poll(self):
        import queue
        try:
            while True:
                item = self.queue.get_nowait()
                if item[0] == "stop":
                    self.root.destroy()
                    return
                self._display(*item[1:])
        except queue.Empty:
            pass
        self.root.after(150, self._poll)

    def _px(self, n):
        return int(round(n * self.scale))

    def _build(self):
        tk = self.tk
        win = tk.Toplevel(self.root)
        win.withdraw()
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.attributes("-alpha", 0.0)
        outer = tk.Frame(win, bg=self.BG, highlightthickness=1,
                         highlightbackground=self.BORDER)
        tk.Frame(outer, bg=self.ACCENT, width=self._px(2)).pack(side="left", fill="y")
        self.label = tk.Label(outer, fg=self.FG, bg=self.BG, anchor="w",
                              font=("Segoe UI", 9), padx=self._px(10), pady=self._px(5))
        self.label.pack(side="left", fill="both", expand=True)
        outer.pack(fill="both", expand=True)
        win.update_idletasks()
        hwnd = int(win.wm_frame(), 16)
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_TOPMOST | WS_EX_TRANSPARENT |
                              WS_EX_TOOLWINDOW | WS_EX_LAYERED | WS_EX_NOACTIVATE)
        self.win = win

    def _cancel(self):
        for job in self.jobs:
            try:
                self.root.after_cancel(job)
            except Exception:
                pass
        self.jobs = []

    def _display(self, title, body, seconds, position):
        if self.win is None:
            self._build()
        self._cancel()  # a new change replaces the current popup
        text = title + (" · " + body if body else "")
        if len(text) > self.MAX_CHARS:
            text = text[:self.MAX_CHARS - 1].rstrip() + "…"
        self.label.config(text=text)
        win = self.win
        win.update_idletasks()
        w = win.winfo_reqwidth()
        h = win.winfo_reqheight()
        area = wt.RECT()
        if not user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(area), 0):
            area = wt.RECT(0, 0, win.winfo_screenwidth(), win.winfo_screenheight() - self._px(48))
        margin = self._px(16)
        x = area.left + margin if "left" in position else area.right - w - margin
        y = area.top + margin if "top" in position else area.bottom - h - margin
        win.geometry("%dx%d+%d+%d" % (w, h, x, y))
        start_alpha = float(win.attributes("-alpha"))
        win.deiconify()
        peak = self.MAX_ALPHA
        self._fade(start_alpha, peak, self.FADE_IN_MS, then=lambda: self.jobs.append(
            self.root.after(int(seconds * 1000),
                            lambda: self._fade(peak, 0.0, self.FADE_OUT_MS, then=win.withdraw))))

    def _fade(self, start, end, ms, then=None, step=0):
        steps = max(1, ms // 15)
        alpha = start + (end - start) * min(1.0, step / steps)
        try:
            self.win.attributes("-alpha", alpha)
        except Exception:
            return
        if step < steps:
            self.jobs.append(self.root.after(15, lambda: self._fade(start, end, ms, then, step + 1)))
        elif then:
            then()


def main():
    dry_run = "--dry-run" in sys.argv
    quiet = "--autostart" in sys.argv  # launched at login: never open windows
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # crisp windows on scaled displays
    except (AttributeError, OSError):
        pass
    ensure_config()
    app = sys.modules[__name__]

    if not dry_run:
        global _instance_lock  # keep the mutex alive for the process lifetime
        _instance_lock = claim_single_instance()
        if _instance_lock is None:
            if quiet:
                log("another copy is already running, exiting")
            else:
                import ui
                ui.run_control(app)
            return
        kernel32.ResetEvent(_stop_event)
        try:
            load_config()
        except (OSError, ValueError, re.error) as e:
            log("config.json has a mistake: %s" % e)
            if not quiet:
                import ui
                ui.show_error("Your settings file has a mistake in it:\n\n%s\n\n"
                              "Fix it, or delete it to start fresh:\n%s" % (e, CONFIG_PATH))
            return
        if not current_client_id():
            if quiet:
                log("no Application ID yet: open the app (or status.py) once to set it up")
                return
            import ui
            if not ui.run_setup(app):
                log("setup cancelled")
                return

    toast = None
    try:
        toast = Toast()  # always created, so "notify" can be switched on live
    except Exception as e:  # no Tk etc: run without popups
        log("popups disabled: %s" % e)

    announce = not quiet and not dry_run
    if toast is None:
        presence_loop(dry_run, None, announce)
        return

    import threading

    def worker():
        try:
            presence_loop(dry_run, toast, announce)
        except Exception as e:
            log("crashed: %r" % e)
        finally:
            toast.stop()

    threading.Thread(target=worker, daemon=True).start()
    toast.run()


def presence_loop(dry_run, toast, announce=False):
    cfg, cfg_mtime = load_config(), os.path.getmtime(CONFIG_PATH)
    last_toast = None
    if toast and announce:
        # Started by hand: confirm it's running, since there's no window.
        toast.show("Discord Status is running",
                   "open it again to stop or change settings" if FROZEN else "",
                   3, cfg.get("notify_position", "bottom-right"))
    ipc = None
    next_connect = 0.0
    current_key, current_payload, started = object(), object(), time.time()
    last_sent_at = 0.0

    log("started%s" % (" (dry run)" if dry_run else ""))
    while True:
        # Hot-reload config.json.
        try:
            mtime = os.path.getmtime(CONFIG_PATH)
            if mtime != cfg_mtime:
                old_id = cfg.get("client_id")
                cfg, cfg_mtime = load_config(), mtime
                current_payload = object()  # force a resend
                log("config reloaded")
                if ipc is not None and cfg.get("client_id") != old_id:
                    ipc.close()  # new Application ID: reconnect with it
                    ipc, next_connect = None, 0.0
        except (OSError, ValueError, re.error) as e:
            log("config error, keeping old config: %s" % e)
            cfg_mtime = mtime

        idle_after = cfg.get("idle_minutes", 0) * 60
        if idle_after and idle_seconds() >= idle_after:
            key, rule, groups = "idle", cfg.get("idle"), {}
        else:
            exe, title, pid = foreground()
            if pid == os.getpid():
                # Our own popup somehow got focus: ignore it entirely.
                key, rule, groups = current_key, {"keep_previous": True}, {}
            else:
                key, rule, groups = match(cfg, exe, title)
                if not rule:
                    key, rule = "default", cfg.get("default")

        if rule and rule.get("keep_previous"):
            # e.g. alt-tabbing into Discord itself: leave the status alone.
            payload = current_payload
        else:
            if key != current_key:
                current_key, started = key, time.time()
            payload = build_activity(rule, groups, started, cfg.get("status_display"))

        if payload != current_payload:
            if dry_run:
                log("would show: %s" % json.dumps(payload))
                current_payload = payload
            elif time.time() - last_sent_at >= 4:  # Discord: max 5 updates / 20s
                if str(cfg.get("client_id", PLACEHOLDER_ID)) in ("", PLACEHOLDER_ID):
                    if time.time() >= next_connect:
                        log("set client_id in config.json first (see README)")
                        next_connect = time.time() + 60
                elif ipc is None and time.time() >= next_connect:
                    try:
                        ipc = DiscordIPC(cfg["client_id"])
                        ipc.connect()
                        log("connected to Discord")
                    except (DiscordError, OSError) as e:
                        log("can't connect: %s" % e)
                        ipc, next_connect = None, time.time() + 15
                if ipc is not None:
                    try:
                        ipc.set_activity(payload)
                        log("showing: %s" % json.dumps(payload))
                        current_payload, last_sent_at = payload, time.time()
                        # Popup only when the visible text changes (not on
                        # reconnects, config reloads or timer resets).
                        text = ((payload or {}).get("details", "status cleared"),
                                (payload or {}).get("state", ""))
                        if toast and cfg.get("notify", True) and text != last_toast:
                            toast.show(text[0], text[1], cfg.get("notify_seconds", 3),
                                       cfg.get("notify_position", "bottom-right"))
                        last_toast = text
                    except ValueError as e:
                        log(str(e))
                        current_payload = payload  # don't spam a bad rule
                    except (DiscordError, OSError, struct.error) as e:
                        log("lost Discord: %s" % e)
                        ipc.close()
                        ipc, next_connect = None, time.time() + 15

        if wait_for_stop(cfg.get("poll_seconds", 3)):
            break

    if ipc is not None:
        ipc.close()  # Discord clears the activity when the pipe closes
    log("stopped")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
