# plaud-audio-sync

Daily sync of Plaud audio files to a local folder.

## Setup

```bash
cp .env.example .env
# edit .env and paste your Plaud bearer token
chmod 600 .env
```

## Run

```bash
python3 sync.py              # download any new files
python3 sync.py --dry-run    # show what would happen
python3 sync.py --limit 1    # only grab one (useful for testing)
python3 sync.py --force      # re-download everything
```

Audio lands in `./audio/` as `YYYY-MM-DD_<name>_<fileId>.mp3`. Already-seen file IDs are
recorded in `state.json` so reruns are cheap.

Set `PLAUD_AUDIO_DIR` in `.env` to override the output location (supports `~` and
relative paths; relative resolves against the script dir).

Uses Python stdlib only — no `pip install` needed.

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

## Endpoints used

- `GET /file/simple/web` — list all files
- `GET /file/detail/{id}` — metadata (for nice filename + date)
- `GET /file/temp-url/{id}` — signed S3 URL for the `.mp3`
