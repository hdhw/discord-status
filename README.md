# discord-status

Your Discord status follows whatever you're doing on your PC. Open VS Code and it says
"coding in my-project"; switch to YouTube and it says "watching YouTube" with the video
title; go idle and it says "afk".

It uses Discord's official Rich Presence (the "Playing ..." card on your profile), so it
doesn't need your account token and isn't a selfbot.

- Windows only
- Python 3.8+ with no extra packages
- Rules live in a JSON file and reload when you save it
- Tray icon with a rules editor, so you don't have to touch JSON
- Optional small popup in the corner whenever your status changes
- Starts with Windows if you want it to

## Quick start (no Python needed)

1. Download **DiscordStatus.exe** from the
   [latest release](https://github.com/lemx33/discord-status/releases/latest).
2. Run it. Windows may show *"Windows protected your PC"* because the app isn't
   code-signed. Click **More info → Run anyway**.
3. The setup window walks you through creating a Discord application and pasting its
   Application ID. Tick **Start with Windows** if you want it running all the time.

While it's running, it has an icon in the system tray next to the clock. On Windows 11, new
icons start out hidden behind the **^** arrow; drag it onto the taskbar to keep it visible.

- **Click** the icon to edit your rules.
- **Right-click** it to see your current status, edit rules, open the log, toggle start with
  Windows, or quit.

Opening `DiscordStatus.exe` again while it's running also shows a small control panel with
the same options.

### Editing rules

**Edit rules** opens a window listing every rule in plain words ("Spotify → Listening to:
picking music"). You can:

- **Add**, **edit**, **delete** and **move** rules. When adding one, **Pick an open app**
  fills in the right .exe name for you, so there's no digging through Task Manager.
- **Test a window** to see which rule an app would use right now. This helps when a rule
  doesn't seem to work because another rule above it wins.
- Set up your away ("afk") status on the **Away** tab. It can say different things
  depending on the time of day (say, "sleeping" between 11pm and 7am) or how long you've
  been gone ("afk" at first, "gone for a while" after an hour).
- Change the "no rule fits" status, the popup and your Application ID on the **General**
  tab.

Changes apply a few seconds after you click **Save**, and the previous version is kept as
`config.backup.json`. The settings live in `%APPDATA%\DiscordStatus\config.json`, and
**Open file in Notepad** edits them by hand (see [Writing rules](#writing-rules)).

## Setup (running from source)

1. **Install Python** from [python.org](https://www.python.org/downloads/). In the
   installer, tick **"Add python.exe to PATH"**.

2. **Download this repo**: use the green **Code → Download ZIP** button and unzip it
   somewhere permanent, or `git clone` it.

3. **Create a Discord application.** This is what shows up as "Playing **name**":
   1. Go to <https://discord.com/developers/applications> and click **New Application**.
   2. Name it whatever you want the top line of your status to say.
   3. Optional: upload an **App Icon**. It's the picture on your status card.
   4. Copy the **Application ID**.

4. **Configure.** Run `start.bat` once and a setup window asks for your Application ID.
   Or copy `config.example.json` to `config.json` yourself and paste the ID into
   `client_id`.

5. **Turn on activity sharing** in Discord: *User Settings → Activity Privacy → Share your
   detected activities with others*.

6. **Run it.** Double-click `start.bat`. It runs in the background with no window.
   `stop.bat` stops it. If nothing shows up, check `status.log` in the same folder.
   Click its tray icon to open the rules editor.

7. **Optional: start with Windows.** Double-click `autostart.bat`. Run
   `autostart.bat remove` from a terminal to undo.

## Writing rules

The rules editor covers the common cases. This section is for editing `config.json` by
hand, or for the editor's "Regular expression" option.

Rules are checked top to bottom, and the first match wins. A rule matches on the focused
window's program (`process`, the .exe name), its title (`title`, a regular expression,
case-insensitive), or both.

```json
{ "process": ["Code.exe"],
  "title": "^(?:● )?(?P<file>.+?) - (?P<folder>.+?) - Visual Studio Code",
  "details": "coding in {folder}", "state": "editing {file}" }
```

Named groups in `title`, like `(?P<file>...)`, can be used as `{file}` in the text.

| Field | What it does |
|---|---|
| `process` | List of .exe names to match (case-insensitive). Leave it out to match any program. |
| `title` | Regex the window title must match. |
| `details` | First line of the status. |
| `state` | Second line of the status. |
| `type` | `0` Playing (default), `2` Listening to, `3` Watching, `5` Competing in. |
| `show_elapsed` | Show the "00:12 elapsed" timer. Default `true`. |
| `large_image` | An image asset name from your app's *Rich Presence → Art Assets*, or an `https://` image link. |
| `large_text` | Tooltip for the image. |
| `buttons` | Up to 2 buttons: `[{"label": "My site", "url": "https://..."}]` |
| `keep_previous` | Matching windows don't change your status at all. Good for private stuff. |

To find a program's .exe name, open Task Manager → *Details* while it's running.

### Top-level settings

| Setting | Default | What it does |
|---|---|---|
| `client_id` | | Your Discord Application ID. |
| `poll_seconds` | `3` | How often to check the focused window. |
| `idle_minutes` | `5` | Switch to the `idle` status after this long without input. `0` turns it off. |
| `idle` / `default` | | Status when you're idle, or when no rule matches. `null` clears it. |
| `idle_rules` | `[]` | Away statuses for particular times or idle lengths, checked before `idle`. See below. |

### Away messages

`idle_rules` works like `rules`: the first one that fits wins, and if none do, `idle` is
used. Each entry takes the same text fields (`details`, `state`, `type`, `show_elapsed`)
plus any of:

| Field | What it does |
|---|---|
| `from` / `to` | Only between these times of day, like `"23:00"` and `"07:00"`. Can cross midnight. |
| `min_minutes` | Only once you've been idle at least this long. |
| `max_minutes` | Only while you've been idle less than this long. |

```json
"idle_rules": [
  { "from": "23:00", "to": "07:00", "details": "sleeping", "state": "zzz" },
  { "min_minutes": 60, "details": "gone for a while" }
]
```

The elapsed timer on an away status counts from when you actually went idle.
| `status_display` | `"details"` | What the member list shows next to your name: `"name"`, `"details"` or `"state"`. |
| `notify` | `true` | Show a popup when your status changes. |
| `notify_seconds` | `2` | How long the popup stays up. |
| `notify_position` | `"bottom-left"` | `bottom-left`, `bottom-right`, `top-left` or `top-right`. |

## Privacy

Your status is visible to everyone who can see your profile, and some rules put window
titles into it (VS Code file names, YouTube video titles, Roblox place names). Remove the
`{...}` parts from rules you don't want to share. Add a `keep_previous` rule at the top for
anything you never want to show. The example config already does this for incognito and
private browser windows.

The script only talks to the Discord app running on your PC. It doesn't send anything
anywhere else, and `status.log` only records the statuses it set.

## Building the exe

Run `build.bat`. It installs PyInstaller into a local `.build-venv` folder (not your main
Python) and writes `dist\DiscordStatus.exe`.

## Troubleshooting

- **Nothing shows on my profile:** check that `client_id` is set, Discord is running, and
  activity sharing is on (setup step 5). Then read `status.log` (next to `status.py`, or
  in `%APPDATA%\DiscordStatus` for the exe).
- **An app shows the default status:** its .exe name doesn't match a rule. Check Task
  Manager → Details and add a rule.
- **Status changes are a bit delayed:** Discord only accepts a few updates every 20
  seconds, so the script waits at least 4 seconds between them.
