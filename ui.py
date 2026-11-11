"""Small Tk windows: first-run setup and the control panel.

`app` is the status module, passed in so this file doesn't import it twice.
"""

import os
import re
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk

PORTAL_URL = "https://discord.com/developers/applications"


def _window(app, title):
    root = tk.Tk()
    root.title(title)
    root.resizable(False, False)
    try:
        root.iconbitmap(app.ICON_PATH)
    except tk.TclError:
        pass
    return root


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


def _apply_autostart(app, enabled):
    try:
        app.set_autostart(enabled)
        return True
    except Exception as e:  # PowerShell blocked, etc.
        messagebox.showwarning("Discord Status",
                               "Couldn't change the start with Windows setting:\n%s" % e)
        return False


def show_error(message):
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror("Discord Status", message, parent=root)
    root.destroy()


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
        "“Share your detected activities with others”."
    )).grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 10))
    ttk.Button(frame, text="Open Developer Portal",
               command=lambda: webbrowser.open(PORTAL_URL)).grid(
        row=2, column=0, columnspan=2, sticky="w", pady=(0, 14))

    ttk.Label(frame, text="Application ID").grid(row=3, column=0, columnspan=2, sticky="w")
    client_id = tk.StringVar(value=app.current_client_id())
    entry = ttk.Entry(frame, textvariable=client_id, width=40)
    entry.grid(row=4, column=0, columnspan=2, sticky="we", pady=(2, 4))
    error = ttk.Label(frame, foreground="#c42b1c", wraplength=wrap)
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
    root = _window(app, "Discord Status")
    frame = ttk.Frame(root, padding=20)
    frame.grid(sticky="nsew")

    ttk.Label(frame, text="Discord Status is running", font=("Segoe UI Semibold", 13)).grid(
        row=0, column=0, columnspan=3, sticky="w")
    ttk.Label(frame, wraplength=360, justify="left", text=(
        "It's working in the background. Your status rules live in a settings file; "
        "changes apply as soon as you save it.")).grid(
        row=1, column=0, columnspan=3, sticky="w", pady=(4, 12))

    autostart = tk.BooleanVar(value=app.autostart_enabled())

    def toggle_autostart():
        if not _apply_autostart(app, autostart.get()):
            autostart.set(app.autostart_enabled())

    ttk.Checkbutton(frame, text="Start with Windows", variable=autostart,
                    command=toggle_autostart).grid(row=2, column=0, columnspan=3,
                                                   sticky="w", pady=(0, 14))

    def open_file(path):
        if os.path.exists(path):
            os.startfile(path)
        else:
            messagebox.showinfo("Discord Status", "Nothing there yet.")

    def stop():
        app.request_stop()
        root.destroy()

    ttk.Button(frame, text="Edit rules", command=lambda: open_file(app.CONFIG_PATH)).grid(
        row=3, column=0, sticky="we")
    ttk.Button(frame, text="Open log", command=lambda: open_file(app.LOG_PATH)).grid(
        row=3, column=1, sticky="we", padx=6)
    ttk.Button(frame, text="Stop", command=stop).grid(row=3, column=2, sticky="we")
    frame.columnconfigure((0, 1, 2), weight=1)

    root.bind("<Escape>", lambda _e: root.destroy())
    _show_centered(root)
    root.mainloop()
