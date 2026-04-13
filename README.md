# plaud-audio-sync

A small Python script that downloads your [Plaud](https://www.plaud.ai/) audio
recordings to a local folder. Run it on demand or on a daily schedule to keep a
local (or Dropbox/iCloud-synced) copy of everything you record — independent of
the Plaud cloud and without relying on the official app.

## Features

- **Incremental** — tracks downloaded file IDs in `state.json`, so reruns only
  fetch what's new
- **Configurable output path** — set `PLAUD_AUDIO_DIR` to point anywhere
  (including a Dropbox/iCloud folder)
- **Resilient** — retries transient API failures (HTTP 429/5xx, network errors)
  with exponential backoff and `Retry-After` support
- **Zero dependencies** — Python 3 stdlib only, no `pip install`
- **Trash-aware** — recordings you deleted in the Plaud app are skipped

## Requirements

- Python 3.9+ (ships with macOS)
- A Plaud account with recordings
- A session token extracted from the Plaud web app (see
  [Obtaining your token](#obtaining-your-token))

## Setup

```bash
cp .env.example .env
chmod 600 .env
# edit .env — paste your token and optionally set PLAUD_AUDIO_DIR
```

## Obtaining your token

Plaud has no official API or developer portal. The token is a JWT session cookie
stored in your browser when you use the Plaud web app.

1. Open [web.plaud.ai](https://web.plaud.ai/) and log in
2. Open your browser's Developer Tools (`F12` or `Cmd+Opt+I`)
3. Go to the **Console** tab and run:
   ```js
   localStorage.getItem("tokenstr")
   ```
4. Copy the full string (starts with `bearer eyJ...`)
5. Paste it into `.env` as the value of `PLAUD_TOKEN` (the script tolerates the
   `bearer ` prefix, so you can paste as-is or strip it)

The token is long-lived (~10 months) but will eventually expire. When it does,
repeat these steps.

## Usage

```bash
python3 sync.py              # download any new files
python3 sync.py --dry-run    # list what would be downloaded
python3 sync.py --limit 1    # only grab one (useful for testing)
python3 sync.py --force      # re-download everything
```

Audio lands in `./audio/` (or `PLAUD_AUDIO_DIR` if set) as
`YYYY-MM-DD_<name>_<fileId>.mp3`. The `fileId` suffix keeps filenames unique
even if you later rename a recording in Plaud.

## Configuration

All config comes from `.env`:

| Variable          | Required | Description                                                                                                 |
| ----------------- | -------- | ----------------------------------------------------------------------------------------------------------- |
| `PLAUD_TOKEN`     | yes      | Your Plaud session token (see above)                                                                        |
| `PLAUD_AUDIO_DIR` | no       | Where audio should land. Supports `~` and relative paths (relative resolves against the script directory).  |

## Schedule daily (macOS)

Create `~/Library/LaunchAgents/com.local.plaud-sync.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.local.plaud-sync</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>/ABSOLUTE/PATH/TO/plaud-audio-sync/sync.py</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>7</integer><key>Minute</key><integer>0</integer></dict>
  <key>StandardOutPath</key><string>/tmp/plaud-sync.log</string>
  <key>StandardErrorPath</key><string>/tmp/plaud-sync.err</string>
</dict>
</plist>
```

Then: `launchctl load ~/Library/LaunchAgents/com.local.plaud-sync.plist`

## API endpoints used

- `GET /file/simple/web` — list all files
- `GET /file/detail/{id}` — metadata (for nice filename + date)
- `GET /file/temp-url/{id}` — signed S3 URL for the `.mp3`

## Legal

This is an unofficial tool, not affiliated with or endorsed by PLAUD, Inc. It
exists to let you retain a local copy of recordings you created. If you don't
have a Plaud account, it won't do anything useful.
