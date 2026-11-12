"""Small Tk windows: first-run setup, the control panel and the rules editor.

`app` is the status module, passed in so this file doesn't import it twice.
"""

import os
import re
import subprocess
import tkinter as tk
import tkinter.font as tkfont
import webbrowser
from tkinter import messagebox, ttk

PORTAL_URL = "https://discord.com/developers/applications"
TITLE = "Discord Status"
HEADING = ("Segoe UI Semibold", 11)
HINT_FG = "#6d6f78"
ERROR_FG = "#c42b1c"

BROWSERS = ["chrome.exe", "msedge.exe", "firefox.exe", "opera.exe", "brave.exe"]
KNOWN_BROWSERS = set(BROWSERS) | {"vivaldi.exe", "librewolf.exe", "zen.exe", "arc.exe",
                                  "waterfox.exe", "floorp.exe", "iexplore.exe"}
ACTIVITY_TYPES = [(0, "Playing"), (2, "Listening to"), (3, "Watching"), (5, "Competing in")]
POSITIONS = ["bottom-left", "bottom-right", "top-left", "top-right"]
SHORT_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
DISPLAYS = [("details", "Line 1"), ("state", "Line 2"), ("name", "The app name")]
_REGEX_CHARS = set(".^$*+?{}[]|()")


def _set_icon(app, win):
    try:
        win.iconbitmap(app.ICON_PATH)
    except tk.TclError:
        pass


def _window(app, title):
    root = tk.Tk()
    root.title(title)
    root.resizable(False, False)
    _set_icon(app, root)
    install_error_report(app, root)
    return root


def install_error_report(app, root):
    """The exe has no console, so a crash in a button would otherwise vanish silently."""
    def report(exc, value, tb):
        import traceback
        app.log("window error:\n" + "".join(traceback.format_exception(exc, value, tb)))
        messagebox.showerror(TITLE, "Something went wrong:\n%s\n\nDetails are in the log:\n%s"
                             % (value, app.LOG_PATH))

    root.report_callback_exception = report


def _show_centered(root):
    root.update_idletasks()
    w, h = root.winfo_reqwidth(), root.winfo_reqheight()
    x = (root.winfo_screenwidth() - w) // 2
    y = (root.winfo_screenheight() - h) // 3
    root.geometry("+%d+%d" % (x, y))
    # Make sure the window comes to the front when launched from Explorer.
    root.lift()
    root.attributes("-topmost", True)
    root.after(300, lambda: root.attributes("-topmost", False))
    root.focus_force()


def _dialog(app, parent, title, resizable=False):
    win = tk.Toplevel(parent)
    win.withdraw()
    win.title(title)
    if parent.winfo_viewable():
        # Not for a hidden parent (opened from the tray): the dialog would stay hidden too.
        win.transient(parent)
    win.resizable(resizable, resizable)
    _set_icon(app, win)
    return win


def _show_dialog(win, parent):
    """Center over the parent (or the screen), make modal and wait until it closes."""
    win.update_idletasks()
    w, h = win.winfo_reqwidth(), win.winfo_reqheight()
    if parent.winfo_viewable():
        x = parent.winfo_rootx() + (parent.winfo_width() - w) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - h) // 3
    else:
        x = (win.winfo_screenwidth() - w) // 2
        y = (win.winfo_screenheight() - h) // 3
    x = max(0, min(x, win.winfo_screenwidth() - w))
    y = max(0, min(y, win.winfo_screenheight() - h - 48))
    win.geometry("+%d+%d" % (x, y))
    win.deiconify()
    if not parent.winfo_viewable():
        win.lift()
        win.attributes("-topmost", True)
        win.after(300, lambda: win.winfo_exists() and win.attributes("-topmost", False))
    win.grab_set()
    win.focus_force()
    parent.wait_window(win)


def _hint(parent, text, **grid):
    label = ttk.Label(parent, text=text, foreground=HINT_FG, wraplength=380, justify="left")
    label.grid(sticky="w", **grid)
    return label


def _apply_autostart(app, enabled):
    try:
        app.set_autostart(enabled)
        return True
    except Exception as e:  # PowerShell blocked, etc.
        messagebox.showwarning(TITLE, "Couldn't change the start with Windows setting:\n%s" % e)
        return False


def open_in_notepad(path):
    subprocess.Popen(["notepad.exe", path])


def show_error(message):
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror(TITLE, message, parent=root)
    root.destroy()


# --------------------------------------------------------------------------
# Describing rules in plain words
# --------------------------------------------------------------------------

def plain_to_regex(text):
    """Like re.escape, but leaves spaces and punctuation readable in the file."""
    return "".join("\\" + c if c in _REGEX_CHARS or c == "\\" else c for c in text)


def regex_to_plain(pattern):
    """Return the literal text a regex matches, or None if it uses regex features."""
    out, i = [], 0
    while i < len(pattern):
        c = pattern[i]
        if c == "\\":
            if i + 1 < len(pattern) and not pattern[i + 1].isalnum():
                out.append(pattern[i + 1])
                i += 2
                continue
            return None
        if c in _REGEX_CHARS:
            return None
        out.append(c)
        i += 1
    return "".join(out)


def _app_names(procs):
    if len(procs) >= 3 and all(p.lower() in KNOWN_BROWSERS for p in procs):
        return "a web browser"
    names = [p[:-4] if p.lower().endswith(".exe") else p for p in procs]
    extra = " +%d more" % (len(names) - 3) if len(names) > 3 else ""
    return ", ".join(names[:3]) + extra


def _describe_title(pattern):
    plain = regex_to_plain(pattern)
    if plain is not None:
        return 'title has "%s"' % plain
    if pattern.startswith("^"):
        plain = regex_to_plain(pattern[1:])
        if plain is not None:
            return 'title starts with "%s"' % plain
    words = [regex_to_plain(p) for p in pattern.split("|")]
    if len(words) > 1 and all(words):
        return "title has " + " or ".join('"%s"' % w for w in words)
    return "title matches  %s" % pattern


def describe_when(rule):
    parts = []
    if rule.get("process"):
        parts.append(_app_names(rule["process"]))
    if rule.get("title"):
        parts.append(_describe_title(rule["title"]))
    return "   +   ".join(parts) or "any window"


def format_clock(minutes):
    """Minutes after midnight as "11 PM" or "7:30 AM"."""
    hour, minute = divmod(minutes % (24 * 60), 60)
    suffix = "AM" if hour < 12 else "PM"
    hour = hour % 12 or 12
    return ("%d %s" % (hour, suffix)) if minute == 0 else ("%d:%02d %s" % (hour, minute, suffix))


def _format_minutes(n):
    n = float(n)
    if n >= 60 and n % 60 == 0:
        return "%d h" % (n // 60)
    return "%g min" % n


def describe_days(app, days):
    try:
        nums = sorted({app.day_number(d) for d in days})
    except ValueError:
        return ", ".join(map(str, days))
    if nums == [0, 1, 2, 3, 4]:
        return "weekdays"
    if nums == [5, 6]:
        return "weekends"
    groups = []  # runs of consecutive days: Mon–Wed
    for n in nums:
        if groups and n == groups[-1][1] + 1:
            groups[-1][1] = n
        else:
            groups.append([n, n])
    out = []
    for a, b in groups:
        if b - a >= 2:
            out.append("%s–%s" % (SHORT_DAYS[a], SHORT_DAYS[b]))
        else:
            out.extend(SHORT_DAYS[a:b + 1])
    return ", ".join(out)


def describe_away_when(app, rule):
    parts = []
    if rule.get("days"):
        parts.append(describe_days(app, rule["days"]))
    if rule.get("from") or rule.get("to"):
        try:
            start = app.clock_minutes(rule["from"]) if rule.get("from") else 0
            end = app.clock_minutes(rule["to"]) if rule.get("to") else 0
            parts.append("%s – %s" % (format_clock(start), format_clock(end)))
        except ValueError:
            parts.append("%s – %s" % (rule.get("from", "?"), rule.get("to", "?")))
    low, high = rule.get("min_minutes"), rule.get("max_minutes")
    if low and high:
        parts.append("away %s to %s" % (_format_minutes(low), _format_minutes(high)))
    elif low:
        parts.append("away %s or more" % _format_minutes(low))
    elif high:
        parts.append("away less than %s" % _format_minutes(high))
    return ",   ".join(parts) or "any time"


def describe_shows(rule):
    if rule.get("keep_previous"):
        return "(leaves your status alone)"
    text = "  ·  ".join(t for t in (rule.get("details"), rule.get("state")) if t)
    verb = dict(ACTIVITY_TYPES).get(rule.get("type", 0), "Playing")
    if verb != "Playing":
        text = "%s:  %s" % (verb, text)
    return text or "(no text)"


# --------------------------------------------------------------------------
# Picking one of the open windows
# --------------------------------------------------------------------------

def pick_window(app, parent):
    """Let the user pick an open window. Returns (exe, title) or None."""
    win = _dialog(app, parent, "Pick a window", resizable=True)
    frame = ttk.Frame(win, padding=14)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, wraplength=520, justify="left", text=(
        "Pick the app you want this rule for. If it isn't listed, open it, "
        "then press Refresh.")).pack(anchor="w", pady=(0, 8))

    box = ttk.Frame(frame)
    box.pack(fill="both", expand=True)
    listbox = tk.Listbox(box, width=80, height=15, activestyle="none", exportselection=False)
    scroll = ttk.Scrollbar(box, orient="vertical", command=listbox.yview)
    listbox.config(yscrollcommand=scroll.set)
    listbox.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")

    windows = []
    result = {}

    def refresh():
        windows[:] = sorted(app.list_windows(), key=lambda w: (w[0].lower(), w[1].lower()))
        listbox.delete(0, "end")
        for exe, title in windows:
            listbox.insert("end", "%s   —   %s" % (exe, title))

    def use(_event=None):
        sel = listbox.curselection()
        if sel:
            result["window"] = windows[sel[0]]
            win.destroy()

    buttons = ttk.Frame(frame)
    buttons.pack(fill="x", pady=(10, 0))
    ttk.Button(buttons, text="Refresh", command=refresh).pack(side="left")
    ttk.Button(buttons, text="Cancel", command=win.destroy).pack(side="right")
    ttk.Button(buttons, text="Use this app", command=use).pack(side="right", padx=(0, 8))
    listbox.bind("<Double-Button-1>", use)
    listbox.bind("<Return>", use)
    win.bind("<Escape>", lambda _e: win.destroy())

    refresh()
    _show_dialog(win, parent)
    return result.get("window")


# --------------------------------------------------------------------------
# Editing one rule
# --------------------------------------------------------------------------

class RuleDialog:
    def __init__(self, app, parent, rule=None):
        self.app, self.parent = app, parent
        self.original = dict(rule or {})
        self.result = None
        r = self.original

        win = self.win = _dialog(app, parent, "Edit rule" if rule else "New rule")
        f = ttk.Frame(win, padding=16)
        f.grid(sticky="nsew")
        f.columnconfigure(1, weight=1)
        width = 48

        # ---- when ----
        ttk.Label(f, text="When I'm using…", font=HEADING).grid(
            row=0, column=0, columnspan=2, sticky="w")

        ttk.Label(f, text="App").grid(row=1, column=0, sticky="w", padx=(0, 10), pady=(8, 0))
        self.apps = tk.StringVar(value=", ".join(r.get("process", [])))
        ttk.Entry(f, textvariable=self.apps, width=width).grid(
            row=1, column=1, sticky="we", pady=(8, 0))
        pick = ttk.Frame(f)
        pick.grid(row=2, column=1, sticky="w", pady=(4, 0))
        ttk.Button(pick, text="Pick an open app…", command=self.pick).pack(side="left")
        ttk.Button(pick, text="Any web browser",
                   command=lambda: self.apps.set(", ".join(BROWSERS))).pack(side="left", padx=(6, 0))
        _hint(f, "The program's .exe name, like Spotify.exe. Separate several with commas. "
                 "Leave it empty to match any app.", row=3, column=1, pady=(2, 0))

        ttk.Label(f, text="Window title").grid(row=4, column=0, sticky="w", padx=(0, 10),
                                               pady=(10, 0))
        pattern = r.get("title", "")
        plain = regex_to_plain(pattern)
        self.regex = tk.BooleanVar(value=plain is None)
        self.title = tk.StringVar(value=pattern if plain is None else plain)
        ttk.Entry(f, textvariable=self.title, width=width).grid(
            row=4, column=1, sticky="we", pady=(10, 0))
        ttk.Checkbutton(f, text="Regular expression (advanced)", variable=self.regex,
                        command=self.toggle_regex).grid(row=5, column=1, sticky="w", pady=(4, 0))
        self.title_hint = _hint(f, "", row=6, column=1, pady=(2, 0))

        # Shown after picking a window, so the title can be copied from it.
        self.seen = tk.StringVar()
        self.seen_label = ttk.Label(f, text="Its title now", foreground=HINT_FG)
        self.seen_entry = ttk.Entry(f, textvariable=self.seen, state="readonly", width=width)

        ttk.Separator(f).grid(row=8, column=0, columnspan=2, sticky="we", pady=14)

        # ---- show ----
        ttk.Label(f, text="…show this", font=HEADING).grid(row=9, column=0, columnspan=2,
                                                           sticky="w")
        self.private = tk.BooleanVar(value=bool(r.get("keep_previous")))
        ttk.Checkbutton(f, text="Nothing: leave my status as it was (for private stuff)",
                        variable=self.private, command=self.update_state).grid(
            row=10, column=0, columnspan=2, sticky="w", pady=(6, 4))

        self.fields = []

        def row(n, label, widget):
            lab = ttk.Label(f, text=label)
            lab.grid(row=n, column=0, sticky="w", padx=(0, 10), pady=(6, 0))
            widget.grid(row=n, column=1, sticky="we", pady=(6, 0))
            self.fields.append(widget)

        names = [name for _, name in ACTIVITY_TYPES]
        self.kind = tk.StringVar(value=dict(ACTIVITY_TYPES).get(r.get("type", 0), "Playing"))
        row(11, "Type", ttk.Combobox(f, textvariable=self.kind, values=names,
                                     state="readonly", width=16))
        self.details = tk.StringVar(value=r.get("details", ""))
        row(12, "Line 1", ttk.Entry(f, textvariable=self.details, width=width))
        self.state = tk.StringVar(value=r.get("state", ""))
        row(13, "Line 2", ttk.Entry(f, textvariable=self.state, width=width))
        self.image = tk.StringVar(value=r.get("large_image", ""))
        row(14, "Picture", ttk.Entry(f, textvariable=self.image, width=width))
        _hint(f, "Optional: an https:// image link, or an Art Asset name from your "
                 "Discord application.", row=15, column=1, pady=(2, 0))
        self.elapsed = tk.BooleanVar(value=r.get("show_elapsed", True))
        check = ttk.Checkbutton(f, text="Show how long I've been doing it", variable=self.elapsed)
        check.grid(row=16, column=1, sticky="w", pady=(6, 0))
        self.fields.append(check)

        preview = ttk.Frame(f, padding=(10, 8), relief="solid", borderwidth=1)
        preview.grid(row=17, column=0, columnspan=2, sticky="we", pady=(12, 0))
        ttk.Label(preview, text="Preview", foreground=HINT_FG).pack(anchor="w")
        self.preview = ttk.Label(preview, justify="left", wraplength=420)
        self.preview.pack(anchor="w")

        self.error = ttk.Label(f, foreground=ERROR_FG, wraplength=420, justify="left")
        self.error.grid(row=18, column=0, columnspan=2, sticky="w", pady=(8, 0))

        buttons = ttk.Frame(f)
        buttons.grid(row=19, column=0, columnspan=2, sticky="e", pady=(8, 0))
        ttk.Button(buttons, text="Cancel", command=win.destroy).pack(side="right")
        ttk.Button(buttons, text="OK", command=self.ok).pack(side="right", padx=(0, 8))
        win.bind("<Return>", self.ok)
        win.bind("<Escape>", lambda _e: win.destroy())

        for var in (self.kind, self.details, self.state, self.title, self.apps):
            var.trace_add("write", lambda *_: self.update_state())
        self.update_state()

    def show(self):
        _show_dialog(self.win, self.parent)
        return self.result

    def pick(self):
        chosen = pick_window(self.app, self.win)
        if chosen:
            exe, title = chosen
            self.apps.set(exe)
            self.seen.set(title)
            self.seen_label.grid(row=7, column=0, sticky="w", padx=(0, 10), pady=(8, 0))
            self.seen_entry.grid(row=7, column=1, sticky="we", pady=(8, 0))

    def toggle_regex(self):
        text = self.title.get()
        if self.regex.get():
            self.title.set(plain_to_regex(text))
        else:
            plain = regex_to_plain(text)
            if plain is None:
                self.regex.set(True)
                messagebox.showinfo(TITLE, "This pattern uses regular expression features, "
                                           "so it can't be turned back into plain text.",
                                    parent=self.win)
                return
            self.title.set(plain)
        self.update_state()

    def update_state(self):
        if self.regex.get():
            self.title_hint.config(text="Matched with Python regex, ignoring case. Named groups "
                                        "like (?P<song>.+) can be shown below as {song}.")
        else:
            self.title_hint.config(text="Only match windows whose title contains this text "
                                        "(any case). Leave empty to match any title.")
        private = self.private.get()
        for widget in self.fields:
            if isinstance(widget, ttk.Combobox):
                widget.config(state="disabled" if private else "readonly")
            else:
                widget.state(["disabled"] if private else ["!disabled"])
        if private:
            self.preview.config(text="Your status stays on whatever it showed before.")
        else:
            lines = ["%s  (your app name)" % self.kind.get()]
            lines += [t for t in (self.details.get().strip(), self.state.get().strip()) if t]
            self.preview.config(text="\n".join(lines))

    def ok(self, _event=None):
        procs = []
        for name in re.split(r"[,;]", self.apps.get()):
            name = name.strip().strip('"')
            if name:
                if "." not in name:
                    name += ".exe"
                procs.append(name)

        title = self.title.get().strip()
        if title and not self.regex.get():
            title = plain_to_regex(title)
        if title:
            try:
                re.compile(title)
            except re.error as e:
                return self.fail("The window title pattern has a mistake: %s" % e)

        private = self.private.get()
        details, state = self.details.get().strip(), self.state.get().strip()
        if not private:
            if not details and not state:
                return self.fail("Type what your status should say in Line 1.")
            for label, text in (("Line 1", details), ("Line 2", state)):
                if len(text) == 1:
                    return self.fail("%s needs at least 2 characters (Discord's rule)." % label)

        if not procs and not title:
            if not messagebox.askyesno(
                    TITLE, "This rule has no app or title, so it fits every window and the "
                           "rules below it will never be used.\n\nKeep it anyway?",
                    parent=self.win):
                return

        rule = {}
        if procs:
            rule["process"] = procs
        if title:
            rule["title"] = title
        if private:
            rule["keep_previous"] = True
        else:
            kind = {name: n for n, name in ACTIVITY_TYPES}[self.kind.get()]
            if kind:
                rule["type"] = kind
            if details:
                rule["details"] = details
            if state:
                rule["state"] = state
            if self.image.get().strip():
                rule["large_image"] = self.image.get().strip()
            if not self.elapsed.get():
                rule["show_elapsed"] = False
        # Keep settings this window doesn't show (buttons, large_text, ...).
        edited = {"process", "title", "keep_previous", "type", "details", "state",
                  "large_image", "show_elapsed"}
        for key, value in self.original.items():
            if key not in edited:
                rule[key] = value
        self.result = rule
        self.win.destroy()

    def fail(self, message):
        self.error.config(text=message)


# --------------------------------------------------------------------------
# Editing one away message
# --------------------------------------------------------------------------

class AwayDialog:
    def __init__(self, app, parent, rule=None):
        self.app, self.parent = app, parent
        self.original = dict(rule or {})
        self.result = None
        r = self.original

        win = self.win = _dialog(app, parent, "Edit away message" if rule else
                                 "New away message")
        f = ttk.Frame(win, padding=16)
        f.grid(sticky="nsew")
        f.columnconfigure(1, weight=1)
        width = 40

        ttk.Label(f, text="Use this when…", font=HEADING).grid(row=0, column=0, columnspan=2,
                                                              sticky="w")

        def clock(key):
            try:
                return format_clock(app.clock_minutes(r[key])) if r.get(key) else ""
            except ValueError:
                return r[key]

        when = ttk.Frame(f)
        when.grid(row=1, column=0, columnspan=2, sticky="w")

        # days of the week
        try:
            days = {app.day_number(d) for d in r.get("days") or []}
        except ValueError:
            days = set()
        self.use_days = tk.BooleanVar(value=bool(days))
        self.day_vars = [tk.BooleanVar(value=(i in days) if days else i < 5) for i in range(7)]
        row = ttk.Frame(when)
        row.grid(row=0, column=0, sticky="w", pady=(8, 0))
        ttk.Checkbutton(row, text="it's a", variable=self.use_days,
                        command=self.update_state).pack(side="left")
        self.day_widgets = []
        for i, name in enumerate(SHORT_DAYS):
            check = ttk.Checkbutton(row, text=name, variable=self.day_vars[i])
            check.pack(side="left", padx=(6 if i == 0 else 0, 2))
            self.day_widgets.append(check)
        quick = ttk.Frame(when)
        quick.grid(row=1, column=0, sticky="w", padx=(22, 0), pady=(4, 0))
        for text, chosen in (("Weekdays", range(5)), ("Weekends", (5, 6)),
                             ("Every day", range(7))):
            button = ttk.Button(quick, text=text, command=lambda c=chosen: self.set_days(c))
            button.pack(side="left", padx=(0, 6))
            self.day_widgets.append(button)

        # time of day
        self.use_time = tk.BooleanVar(value=bool(r.get("from") or r.get("to")))
        self.start = tk.StringVar(value=clock("from") or "11 PM")
        self.end = tk.StringVar(value=clock("to") or "7 AM")
        row = ttk.Frame(when)
        row.grid(row=2, column=0, sticky="w", pady=(10, 0))
        ttk.Checkbutton(row, text="it's between", variable=self.use_time,
                        command=self.update_state).pack(side="left")
        self.start_entry = ttk.Entry(row, textvariable=self.start, width=9)
        self.start_entry.pack(side="left", padx=6)
        ttk.Label(row, text="and").pack(side="left")
        self.end_entry = ttk.Entry(row, textvariable=self.end, width=9)
        self.end_entry.pack(side="left", padx=6)
        ttk.Label(when, foreground=HINT_FG, wraplength=380, justify="left", text=(
            "Like 11pm and 7am, or 23:00 and 07:00. It can go past midnight: Friday 11pm "
            "to 7am still counts as Friday at 2am.")).grid(
            row=3, column=0, sticky="w", padx=(22, 0))

        # how long away
        self.use_min = tk.BooleanVar(value=bool(r.get("min_minutes")))
        self.low = tk.StringVar(value="%g" % r["min_minutes"] if r.get("min_minutes") else "30")
        row = ttk.Frame(f)
        row.grid(row=3, column=0, columnspan=2, sticky="w", pady=(10, 0))
        ttk.Checkbutton(row, text="I've been away at least", variable=self.use_min,
                        command=self.update_state).pack(side="left")
        self.low_entry = ttk.Spinbox(row, from_=1, to=1440, textvariable=self.low, width=6)
        self.low_entry.pack(side="left", padx=6)
        ttk.Label(row, text="minutes").pack(side="left")

        self.use_max = tk.BooleanVar(value=bool(r.get("max_minutes")))
        self.high = tk.StringVar(value="%g" % r["max_minutes"] if r.get("max_minutes")
                                 else "60")
        row = ttk.Frame(f)
        row.grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Checkbutton(row, text="I've been away less than", variable=self.use_max,
                        command=self.update_state).pack(side="left")
        self.high_entry = ttk.Spinbox(row, from_=1, to=1440, textvariable=self.high, width=6)
        self.high_entry.pack(side="left", padx=6)
        ttk.Label(row, text="minutes").pack(side="left")
        _hint(f, "Tick more than one and they all have to be true.", row=5, column=0,
              columnspan=2, pady=(6, 0))

        ttk.Separator(f).grid(row=6, column=0, columnspan=2, sticky="we", pady=14)

        ttk.Label(f, text="…show this", font=HEADING).grid(row=7, column=0, columnspan=2,
                                                           sticky="w")

        def field(n, label, widget):
            ttk.Label(f, text=label).grid(row=n, column=0, sticky="w", padx=(0, 10), pady=(6, 0))
            widget.grid(row=n, column=1, sticky="we", pady=(6, 0))

        self.kind = tk.StringVar(value=dict(ACTIVITY_TYPES).get(r.get("type", 0), "Playing"))
        field(8, "Type", ttk.Combobox(f, textvariable=self.kind, state="readonly", width=16,
                                      values=[name for _, name in ACTIVITY_TYPES]))
        self.details = tk.StringVar(value=r.get("details", ""))
        field(9, "Line 1", ttk.Entry(f, textvariable=self.details, width=width))
        self.state = tk.StringVar(value=r.get("state", ""))
        field(10, "Line 2", ttk.Entry(f, textvariable=self.state, width=width))
        self.elapsed = tk.BooleanVar(value=r.get("show_elapsed", True))
        ttk.Checkbutton(f, text="Show how long I've been away", variable=self.elapsed).grid(
            row=11, column=1, sticky="w", pady=(6, 0))

        self.error = ttk.Label(f, foreground=ERROR_FG, wraplength=380, justify="left")
        self.error.grid(row=12, column=0, columnspan=2, sticky="w", pady=(8, 0))
        buttons = ttk.Frame(f)
        buttons.grid(row=13, column=0, columnspan=2, sticky="e", pady=(8, 0))
        ttk.Button(buttons, text="Cancel", command=win.destroy).pack(side="right")
        ttk.Button(buttons, text="OK", command=self.ok).pack(side="right", padx=(0, 8))
        win.bind("<Return>", self.ok)
        win.bind("<Escape>", lambda _e: win.destroy())
        self.update_state()

    def update_state(self):
        for flag, widgets in ((self.use_days, self.day_widgets),
                              (self.use_time, (self.start_entry, self.end_entry)),
                              (self.use_min, (self.low_entry,)),
                              (self.use_max, (self.high_entry,))):
            for widget in widgets:
                widget.state(["!disabled"] if flag.get() else ["disabled"])

    def set_days(self, chosen):
        for i, var in enumerate(self.day_vars):
            var.set(i in chosen)

    def show(self):
        _show_dialog(self.win, self.parent)
        return self.result

    def fail(self, message):
        self.error.config(text=message)

    def ok(self, _event=None):
        rule = {}
        if self.use_days.get():
            days = [self.app.DAY_NAMES[i] for i, var in enumerate(self.day_vars) if var.get()]
            if not days:
                return self.fail("Pick at least one day, or untick “it's a”.")
            if len(days) < 7:  # all seven is the same as not limiting it
                rule["days"] = days
        if self.use_time.get():
            try:
                start = self.app.clock_minutes(self.start.get())
                end = self.app.clock_minutes(self.end.get())
            except ValueError as e:
                return self.fail(str(e)[:1].upper() + str(e)[1:] + ".")
            if start == end:
                return self.fail("The start and end time are the same.")
            rule["from"] = "%02d:%02d" % divmod(start, 60)
            rule["to"] = "%02d:%02d" % divmod(end, 60)
        for flag, var, key in ((self.use_min, self.low, "min_minutes"),
                               (self.use_max, self.high, "max_minutes")):
            if flag.get():
                try:
                    n = float(var.get())
                except ValueError:
                    return self.fail("Minutes have to be a number.")
                if n <= 0:
                    return self.fail("Minutes have to be more than 0.")
                rule[key] = int(n) if n.is_integer() else n
        if rule.get("min_minutes") and rule.get("max_minutes") and \
                rule["min_minutes"] >= rule["max_minutes"]:
            return self.fail("“At least” has to be smaller than “less than”, or it can "
                             "never be true.")

        details, state = self.details.get().strip(), self.state.get().strip()
        if not details and not state:
            return self.fail("Type what your status should say in Line 1.")
        for label, text in (("Line 1", details), ("Line 2", state)):
            if len(text) == 1:
                return self.fail("%s needs at least 2 characters (Discord's rule)." % label)
        if not rule and not messagebox.askyesno(
                TITLE, "Nothing is ticked under “Use this when”, so this message is always "
                       "used and the ones below it never are.\n\nKeep it anyway?",
                parent=self.win):
            return

        kind = {name: n for n, name in ACTIVITY_TYPES}[self.kind.get()]
        if kind:
            rule["type"] = kind
        if details:
            rule["details"] = details
        if state:
            rule["state"] = state
        if not self.elapsed.get():
            rule["show_elapsed"] = False
        edited = {"days", "from", "to", "min_minutes", "max_minutes", "type", "details",
                  "state", "show_elapsed"}
        for key, value in self.original.items():
            if key not in edited:
                rule[key] = value
        self.result = rule
        self.win.destroy()


# --------------------------------------------------------------------------
# The rules editor
# --------------------------------------------------------------------------

class RulesEditor:
    def __init__(self, app, parent):
        self.app, self.parent = app, parent
        self.cfg = app.read_config()
        self.rules = [dict(r) for r in self.cfg.get("rules", [])]
        self.away = [dict(r) for r in self.cfg.get("idle_rules", [])]
        self.dirty = False
        self.vars = []

        win = self.win = _dialog(app, parent, "Discord Status rules", resizable=True)
        win.protocol("WM_DELETE_WINDOW", self.close)
        outer = ttk.Frame(win, padding=12)
        outer.pack(fill="both", expand=True)

        notebook = self.notebook = ttk.Notebook(outer)
        notebook.pack(fill="both", expand=True)
        self.tabs = {}
        for name, build in (("Rules", self._rules_tab), ("Away", self._away_tab),
                            ("General", self._general_tab)):
            self.tabs[name] = build(notebook)
            notebook.add(self.tabs[name], text="  %s  " % name)

        bottom = ttk.Frame(outer)
        bottom.pack(fill="x", pady=(10, 0))
        ttk.Button(bottom, text="Open file in Notepad", command=self.notepad).pack(side="left")
        self.status = ttk.Label(bottom, foreground=HINT_FG)
        self.status.pack(side="left", padx=10)
        ttk.Button(bottom, text="Close", command=self.close).pack(side="right")
        ttk.Button(bottom, text="Save", command=self.save).pack(side="right", padx=(0, 8))
        win.bind("<Control-s>", lambda _e: self.save())

        self.refresh()
        self.refresh_away()
        self.dirty = False

    def _var(self, kind, value):
        v = kind(value=value)
        v.trace_add("write", lambda *_: self.changed())
        self.vars.append(v)
        return v

    def _make_list(self, parent, columns, height):
        """A Treeview with a scrollbar; `columns` is [(id, heading, width)]."""
        line = tkfont.nametofont("TkDefaultFont").metrics("linespace")
        ttk.Style(parent).configure("Rules.Treeview", rowheight=line + 8)
        box = ttk.Frame(parent)
        tree = ttk.Treeview(box, columns=[c[0] for c in columns], show="headings",
                            height=height, selectmode="browse", style="Rules.Treeview")
        for col, text, width in columns:
            tree.heading(col, text=text, anchor="w")
            tree.column(col, width=width, minwidth=30, stretch=col != "n", anchor="w")
        scroll = ttk.Scrollbar(box, orient="vertical", command=tree.yview)
        tree.config(yscrollcommand=scroll.set)
        tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        return box, tree

    # ---- away tab ----
    def _away_tab(self, notebook):
        cfg = self.cfg
        tab = ttk.Frame(notebook, padding=12)
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(2, weight=1)

        top = ttk.Frame(tab)
        top.grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(top, text="Count me as away after").pack(side="left")
        self.v_idle_min = self._var(tk.StringVar, str(cfg.get("idle_minutes", 5)))
        ttk.Spinbox(top, from_=0, to=240, textvariable=self.v_idle_min, width=5).pack(
            side="left", padx=6)
        ttk.Label(top, text="minutes without touching the mouse or keyboard (0 = never)",
                  foreground=HINT_FG).pack(side="left")

        ttk.Label(tab, wraplength=640, justify="left", text=(
            "Your away status can change with the time of day, or with how long you've been "
            "gone. The first message that fits is used.")).grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(12, 8))

        box, tree = self._make_list(tab, [("n", "#", 40), ("when", "Use when", 300),
                                          ("shows", "My status says", 320)], height=7)
        box.grid(row=2, column=0, sticky="nsew")
        self.away_tree = tree
        tree.bind("<Double-1>", lambda _e: self.away_edit())
        tree.bind("<Return>", lambda _e: self.away_edit())
        tree.bind("<Delete>", lambda _e: self.away_delete())

        side = ttk.Frame(tab)
        side.grid(row=2, column=1, sticky="n", padx=(10, 0))
        for text, command in (("Add…", self.away_add), ("Edit…", self.away_edit),
                              ("Delete", self.away_delete), (None, None),
                              ("Move up", lambda: self.away_move(-1)),
                              ("Move down", lambda: self.away_move(1))):
            if text is None:
                ttk.Frame(side, height=12).pack()
            else:
                ttk.Button(side, text=text, command=command, width=16).pack(fill="x", pady=2)

        idle = cfg.get("idle") or {}
        ttk.Label(tab, text="If none of those fit", font=HEADING).grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(14, 2))
        rest = ttk.Frame(tab)
        rest.grid(row=4, column=0, sticky="we")
        rest.columnconfigure(1, weight=1)
        self.v_idle1 = self._var(tk.StringVar, idle.get("details", ""))
        self.v_idle2 = self._var(tk.StringVar, idle.get("state", ""))
        for n, (label, var) in enumerate((("Line 1", self.v_idle1), ("Line 2", self.v_idle2))):
            ttk.Label(rest, text=label).grid(row=n, column=0, sticky="w", padx=(0, 12), pady=3)
            ttk.Entry(rest, textvariable=var, width=40).grid(row=n, column=1, sticky="we",
                                                             pady=3)
        return tab

    def refresh_away(self, select=None):
        tree = self.away_tree
        tree.delete(*tree.get_children())
        for i, rule in enumerate(self.away):
            tree.insert("", "end", iid=str(i), values=(
                i + 1, describe_away_when(self.app, rule), describe_shows(rule)))
        if select is not None and self.away:
            iid = str(max(0, min(select, len(self.away) - 1)))
            tree.selection_set(iid)
            tree.focus(iid)
            tree.see(iid)

    def _away_selected(self):
        sel = self.away_tree.selection()
        return int(sel[0]) if sel else None

    def away_add(self):
        rule = AwayDialog(self.app, self.win).show()
        if rule is not None:
            index = self._away_selected()
            index = 0 if index is None else index
            self.away.insert(index, rule)
            self.refresh_away(select=index)
            self.changed()

    def away_edit(self):
        index = self._away_selected()
        if index is not None:
            rule = AwayDialog(self.app, self.win, self.away[index]).show()
            if rule is not None:
                self.away[index] = rule
                self.refresh_away(select=index)
                self.changed()

    def away_delete(self):
        index = self._away_selected()
        if index is not None and messagebox.askyesno(
                TITLE, "Delete this away message?\n\n%s\n→ %s" % (
                    describe_away_when(self.app, self.away[index]),
                    describe_shows(self.away[index])), parent=self.win):
            del self.away[index]
            self.refresh_away(select=index)
            self.changed()

    def away_move(self, step):
        index = self._away_selected()
        if index is not None and 0 <= index + step < len(self.away):
            self.away[index], self.away[index + step] = self.away[index + step], self.away[index]
            self.refresh_away(select=index + step)
            self.changed()

    # ---- rules tab ----
    def _rules_tab(self, notebook):
        tab = ttk.Frame(notebook, padding=12)
        ttk.Label(tab, wraplength=640, justify="left", text=(
            "Rules are checked from the top down, and the first one that fits the window "
            "you're using sets your status. Put specific rules above general ones.")).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

        line = tkfont.nametofont("TkDefaultFont").metrics("linespace")
        ttk.Style(tab).configure("Rules.Treeview", rowheight=line + 8)
        box = ttk.Frame(tab)
        box.grid(row=1, column=0, sticky="nsew")
        tree = self.tree = ttk.Treeview(box, columns=("n", "when", "shows"), show="headings",
                                        height=16, selectmode="browse", style="Rules.Treeview")
        for col, text, width, stretch in (("n", "#", 40, False), ("when", "When I'm using", 300, True),
                                          ("shows", "My status says", 320, True)):
            tree.heading(col, text=text, anchor="w")
            tree.column(col, width=width, minwidth=30, stretch=stretch, anchor="w")
        scroll = ttk.Scrollbar(box, orient="vertical", command=tree.yview)
        tree.config(yscrollcommand=scroll.set)
        tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        tree.bind("<Double-1>", lambda _e: self.edit())
        tree.bind("<Return>", lambda _e: self.edit())
        tree.bind("<Delete>", lambda _e: self.delete())

        side = ttk.Frame(tab)
        side.grid(row=1, column=1, sticky="n", padx=(10, 0))
        for text, command in (("Add…", self.add), ("Edit…", self.edit), ("Delete", self.delete),
                              (None, None), ("Move up", lambda: self.move(-1)),
                              ("Move down", lambda: self.move(1)), (None, None),
                              ("Test a window…", self.test)):
            if text is None:
                ttk.Frame(side, height=12).pack()
            else:
                ttk.Button(side, text=text, command=command, width=16).pack(fill="x", pady=2)
        _hint(tab, "New rules go above the selected one. “Test a window” shows which rule "
                   "an app would use.", row=2, column=0, columnspan=2, pady=(8, 0))
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)
        return tab

    def selected(self):
        sel = self.tree.selection()
        return int(sel[0]) if sel else None

    def refresh(self, select=None):
        tree = self.tree
        tree.delete(*tree.get_children())
        for i, rule in enumerate(self.rules):
            tree.insert("", "end", iid=str(i),
                        values=(i + 1, describe_when(rule), describe_shows(rule)))
        if select is not None and self.rules:
            iid = str(max(0, min(select, len(self.rules) - 1)))
            tree.selection_set(iid)
            tree.focus(iid)
            tree.see(iid)

    def changed(self):
        self.dirty = True
        self.status.config(text="Unsaved changes", foreground=HINT_FG)

    def add(self):
        rule = RuleDialog(self.app, self.win).show()
        if rule is None:
            return
        index = self.selected()
        if index is None:
            # Below the private "leave my status alone" rules at the top, so a new
            # website rule doesn't override them.
            index = 0
            while index < len(self.rules) and self.rules[index].get("keep_previous"):
                index += 1
        self.rules.insert(index, rule)
        self.refresh(select=index)
        self.changed()

    def edit(self):
        index = self.selected()
        if index is None:
            return
        rule = RuleDialog(self.app, self.win, self.rules[index]).show()
        if rule is not None:
            self.rules[index] = rule
            self.refresh(select=index)
            self.changed()

    def delete(self):
        index = self.selected()
        if index is None:
            return
        rule = self.rules[index]
        if messagebox.askyesno(TITLE, "Delete this rule?\n\n%s\n→ %s" % (
                describe_when(rule), describe_shows(rule)), parent=self.win):
            del self.rules[index]
            self.refresh(select=index)
            self.changed()

    def move(self, step):
        index = self.selected()
        if index is None:
            return
        target = index + step
        if 0 <= target < len(self.rules):
            self.rules[index], self.rules[target] = self.rules[target], self.rules[index]
            self.refresh(select=target)
            self.changed()

    def test(self):
        chosen = pick_window(self.app, self.win)
        if not chosen:
            return
        exe, title = chosen
        try:
            compiled = self.app.compile_rules(self.rules)
        except re.error as e:
            messagebox.showerror(TITLE, "One of the rules has a broken title pattern: %s" % e,
                                 parent=self.win)
            return
        key, rule, groups = self.app.match({"rules": compiled}, exe, title)
        window = "%s — %s" % (exe, title)
        if rule is None:
            self.tree.selection_set(())
            messagebox.showinfo(TITLE, "%s\n\nNo rule fits this window, so it shows your "
                                       "\"nothing matches\" status from the General tab."
                                % window, parent=self.win)
            return
        index = int(key[4:])
        self.refresh(select=index)
        if rule.get("keep_previous"):
            says = "leaves your status as it was"
        else:
            lines = [rule[f].format_map(self.app._Blank(groups)).strip()
                     for f in ("details", "state") if rule.get(f)]
            says = "shows:\n    " + "\n    ".join(lines)
        messagebox.showinfo(TITLE, "%s\n\nUses rule #%d, which %s" % (window, index + 1, says),
                            parent=self.win)

    # ---- general tab ----
    def _general_tab(self, notebook):
        cfg = self.cfg
        tab = ttk.Frame(notebook, padding=14)
        tab.columnconfigure(1, weight=1)
        var = self._var

        def section(row, text, pady=(0, 0)):
            ttk.Label(tab, text=text, font=HEADING).grid(row=row, column=0, columnspan=3,
                                                          sticky="w", pady=pady)

        def field(row, label, widget, **grid):
            ttk.Label(tab, text=label).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=3)
            widget.grid(row=row, column=1, sticky=grid.get("sticky", "we"), pady=3)

        client = str(cfg.get("client_id", ""))
        if client == self.app.PLACEHOLDER_ID:
            client = ""
        section(0, "Discord")
        self.v_client = var(tk.StringVar, client)
        field(1, "Application ID", ttk.Entry(tab, textvariable=self.v_client, width=30),
              sticky="w")
        display = dict(DISPLAYS).get(cfg.get("status_display"), "Line 1")
        self.v_display = var(tk.StringVar, display)
        field(2, "Member list shows", ttk.Combobox(
            tab, textvariable=self.v_display, values=[n for _, n in DISPLAYS],
            state="readonly", width=16), sticky="w")

        default = cfg.get("default")
        section(3, "When no rule fits", pady=(14, 0))
        self.v_default_on = var(tk.BooleanVar, default is not None)
        ttk.Checkbutton(tab, text="Show a status (otherwise it's cleared)",
                        variable=self.v_default_on).grid(row=4, column=0, columnspan=2,
                                                         sticky="w", pady=3)
        self.v_default1 = var(tk.StringVar, (default or {}).get("details", ""))
        field(5, "Line 1", ttk.Entry(tab, textvariable=self.v_default1, width=40))
        self.v_default2 = var(tk.StringVar, (default or {}).get("state", ""))
        field(6, "Line 2", ttk.Entry(tab, textvariable=self.v_default2, width=40))

        section(11, "Popup", pady=(14, 0))
        self.v_notify = var(tk.BooleanVar, bool(cfg.get("notify", True)))
        ttk.Checkbutton(tab, text="Show a small popup when my status changes",
                        variable=self.v_notify).grid(row=12, column=0, columnspan=2,
                                                     sticky="w", pady=3)
        self.v_notify_secs = var(tk.StringVar, str(cfg.get("notify_seconds", 2)))
        seconds = ttk.Frame(tab)
        ttk.Spinbox(seconds, from_=1, to=30, textvariable=self.v_notify_secs, width=5).pack(
            side="left")
        ttk.Label(seconds, text="seconds", foreground=HINT_FG).pack(side="left", padx=(8, 0))
        field(13, "Stays for", seconds, sticky="w")
        self.v_position = var(tk.StringVar, cfg.get("notify_position", "bottom-left"))
        field(14, "Corner", ttk.Combobox(tab, textvariable=self.v_position, values=POSITIONS,
                                         state="readonly", width=16), sticky="w")
        return tab

    def _status_block(self, original, details, state):
        block = dict(original or {})
        for key, value in (("details", details.strip()), ("state", state.strip())):
            if value:
                block[key] = value
            else:
                block.pop(key, None)
        return block

    def _apply_general(self):
        """Copy the Away and General tabs into self.cfg.
        Returns None, or (tab name, error message)."""
        cfg = self.cfg
        client = re.sub(r"\s+", "", self.v_client.get())
        if not re.fullmatch(r"\d{17,20}", client):
            return "General", "The Application ID should be a long number (17–20 digits)."
        try:
            idle_minutes = float(self.v_idle_min.get())
        except ValueError:
            return "Away", "The away minutes have to be a number."
        try:
            notify_seconds = float(self.v_notify_secs.get())
        except ValueError:
            return "General", "The popup seconds have to be a number."
        if idle_minutes < 0:
            return "Away", "The away minutes can't be negative."
        if notify_seconds <= 0:
            return "General", "The popup seconds have to be more than 0."
        for tab, label, text in (("General", "No-rule Line 1", self.v_default1.get()),
                                 ("General", "No-rule Line 2", self.v_default2.get()),
                                 ("Away", "Away Line 1", self.v_idle1.get()),
                                 ("Away", "Away Line 2", self.v_idle2.get())):
            if len(text.strip()) == 1:
                return tab, "%s needs at least 2 characters (Discord's rule)." % label

        cfg["client_id"] = client
        cfg["status_display"] = {n: key for key, n in DISPLAYS}[self.v_display.get()]
        cfg["idle_minutes"] = int(idle_minutes) if idle_minutes.is_integer() else idle_minutes
        cfg["notify"] = self.v_notify.get()
        cfg["notify_seconds"] = (int(notify_seconds) if notify_seconds.is_integer()
                                 else notify_seconds)
        cfg["notify_position"] = self.v_position.get()
        if self.v_default_on.get():
            cfg["default"] = self._status_block(cfg.get("default"), self.v_default1.get(),
                                                self.v_default2.get())
        else:
            cfg["default"] = None
        cfg["idle"] = self._status_block(cfg.get("idle"), self.v_idle1.get(),
                                         self.v_idle2.get())
        if self.away or "idle_rules" in cfg:
            cfg["idle_rules"] = self.away
        return None

    # ---- saving ----
    def save(self):
        error = self._apply_general()
        if error:
            self.notebook.select(self.tabs[error[0]])
            messagebox.showerror(TITLE, error[1], parent=self.win)
            return False
        self.cfg["rules"] = self.rules
        try:
            self.app.write_config(self.cfg)
        except (OSError, ValueError) as e:
            messagebox.showerror(TITLE, "Couldn't save: %s" % e, parent=self.win)
            return False
        self.dirty = False
        self.status.config(text="Saved. Your status updates in a few seconds.",
                           foreground="#2d7d46")
        return True

    def ask_save(self):
        """Returns False if the user cancelled."""
        if not self.dirty:
            return True
        answer = messagebox.askyesnocancel(TITLE, "Save your changes?", parent=self.win)
        if answer is None:
            return False
        return self.save() if answer else True

    def close(self):
        if self.ask_save():
            self.win.destroy()

    def notepad(self):
        if self.ask_save():
            open_in_notepad(self.app.CONFIG_PATH)
            self.win.destroy()

    def show(self):
        self.win.update_idletasks()
        self.win.minsize(self.win.winfo_reqwidth(), self.win.winfo_reqheight())
        _show_dialog(self.win, self.parent)


_open_editor = None


def open_rules_editor(app, parent):
    """Open the rules editor, or bring it to the front if it's already open."""
    global _open_editor
    if _open_editor is not None and _open_editor.win.winfo_exists():
        win = _open_editor.win
        win.deiconify()
        win.lift()
        win.focus_force()
        return
    install_error_report(app, parent)
    try:
        _open_editor = RulesEditor(app, parent)
    except (OSError, ValueError) as e:
        if messagebox.askyesno(TITLE, "Your settings file has a mistake, so the editor can't "
                                      "open it:\n\n%s\n\nOpen it in Notepad to fix it?" % e,
                               parent=parent):
            open_in_notepad(app.CONFIG_PATH)
        return
    try:
        _open_editor.show()
    finally:
        _open_editor = None


# --------------------------------------------------------------------------
# First run and control panel
# --------------------------------------------------------------------------

def run_setup(app):
    """First-run window. Returns True if the user saved an ID and pressed Start."""
    root = _window(app, "Discord Status setup")
    frame = ttk.Frame(root, padding=20)
    frame.grid(sticky="nsew")
    wrap = 400

    ttk.Label(frame, text="Discord Status", font=("Segoe UI Semibold", 15)).grid(
        row=0, column=0, columnspan=2, sticky="w")
    ttk.Label(frame, wraplength=wrap, justify="left", text=(
        "Your Discord status will follow whatever you're doing on your PC.\n\n"
        "1.  Create an application in the Discord Developer Portal. Its name is what "
        "your status will say you're playing.\n"
        "2.  Copy its Application ID and paste it below.\n"
        "3.  In Discord, go to User Settings → Activity Privacy and turn on "
        "“Share your detected activities with others”.\n\n"
        "To change your rules later, open this app again while it's running."
    )).grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 10))
    ttk.Button(frame, text="Open Developer Portal",
               command=lambda: webbrowser.open(PORTAL_URL)).grid(
        row=2, column=0, columnspan=2, sticky="w", pady=(0, 14))

    ttk.Label(frame, text="Application ID").grid(row=3, column=0, columnspan=2, sticky="w")
    client_id = tk.StringVar(value=app.current_client_id())
    entry = ttk.Entry(frame, textvariable=client_id, width=40)
    entry.grid(row=4, column=0, columnspan=2, sticky="we", pady=(2, 4))
    error = ttk.Label(frame, foreground=ERROR_FG, wraplength=wrap)
    error.grid(row=5, column=0, columnspan=2, sticky="w")

    autostart = tk.BooleanVar(value=True)
    ttk.Checkbutton(frame, text="Start with Windows", variable=autostart).grid(
        row=6, column=0, columnspan=2, sticky="w", pady=(6, 14))

    result = {"start": False}

    def start(_event=None):
        value = re.sub(r"\s+", "", client_id.get())
        if not re.fullmatch(r"\d{17,20}", value):
            error.config(text="That doesn't look like an Application ID. "
                              "It's a long number (17–20 digits).")
            return
        try:
            app.save_client_id(value)
        except (OSError, ValueError) as e:
            error.config(text="Couldn't save settings: %s" % e)
            return
        _apply_autostart(app, autostart.get())
        result["start"] = True
        root.destroy()

    buttons = ttk.Frame(frame)
    buttons.grid(row=7, column=0, columnspan=2, sticky="e")
    ttk.Button(buttons, text="Cancel", command=root.destroy).pack(side="right")
    ttk.Button(buttons, text="Start", command=start).pack(side="right", padx=(0, 8))
    entry.bind("<Return>", start)

    _show_centered(root)
    entry.focus_set()
    root.mainloop()
    return result["start"]


def run_control(app):
    """Shown when the app is opened while it's already running."""
    root = _window(app, TITLE)
    frame = ttk.Frame(root, padding=20)
    frame.grid(sticky="nsew")

    ttk.Label(frame, text="Discord Status is running", font=("Segoe UI Semibold", 13)).grid(
        row=0, column=0, columnspan=3, sticky="w")
    ttk.Label(frame, wraplength=360, justify="left", text=(
        "It's working in the background, with an icon in the system tray (you may need to "
        "click ^ next to the clock to see it). Use Edit rules to change what your status "
        "says for each app; changes apply as soon as you save.")).grid(
        row=1, column=0, columnspan=3, sticky="w", pady=(4, 12))

    autostart = tk.BooleanVar(value=app.autostart_enabled())

    def toggle_autostart():
        if not _apply_autostart(app, autostart.get()):
            autostart.set(app.autostart_enabled())

    ttk.Checkbutton(frame, text="Start with Windows", variable=autostart,
                    command=toggle_autostart).grid(row=2, column=0, columnspan=3,
                                                   sticky="w", pady=(0, 14))

    def open_log():
        if os.path.exists(app.LOG_PATH):
            open_in_notepad(app.LOG_PATH)
        else:
            messagebox.showinfo(TITLE, "Nothing logged yet.", parent=root)

    def stop():
        app.request_stop()
        root.destroy()

    ttk.Button(frame, text="Edit rules", command=lambda: open_rules_editor(app, root)).grid(
        row=3, column=0, sticky="we")
    ttk.Button(frame, text="Open log", command=open_log).grid(row=3, column=1, sticky="we",
                                                              padx=6)
    ttk.Button(frame, text="Stop", command=stop).grid(row=3, column=2, sticky="we")
    frame.columnconfigure((0, 1, 2), weight=1)

    root.bind("<Escape>", lambda _e: root.destroy())
    _show_centered(root)
    root.mainloop()
