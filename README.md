# Codex MSU2 Mini display

Show the locally authenticated Codex rolling allowance on a 160×80
MSU2_MINI USB screen connected to macOS.

The stable display mode uses the firmware's native drawing commands:

- large green remaining percentage;
- small vector text such as `RESET 08-20`;
- Codex usage query every 60 seconds;
- lightweight glyph redraw to suppress the built-in flower animation;
- automatic USB reconnect;
- no P25D80 Flash erase or write during normal operation.

The protocol was recovered from the supplied `MSU2_MINI_DemoV1.6` host
application and checked against the MSU2 development manual.

## Requirements

- macOS with Python 3.10 or newer;
- Codex CLI installed and authenticated;
- MSU2_MINI available as `/dev/cu.usbmodem*`.

No third-party Python packages are required.

## Run

```bash
cd ~/Desktop/codex/codex-msu2-display
python3 codex_msu2_native.py
```

For a specific device:

```bash
python3 codex_msu2_native.py \
  --device-glob /dev/cu.usbmodem01234567891 \
  --interval 60 \
  --draw-interval 0.2
```

Press `Ctrl-C` to stop.

## Start automatically after login

```bash
cp com.hanxiaobo.codex-msu2-display.plist ~/Library/LaunchAgents/
launchctl bootstrap "gui/$(id -u)" \
  ~/Library/LaunchAgents/com.hanxiaobo.codex-msu2-display.plist
```

Restart the service:

```bash
launchctl kickstart -k gui/$(id -u)/com.hanxiaobo.codex-msu2-display
```

Stop and disable it:

```bash
launchctl bootout "gui/$(id -u)" \
  ~/Library/LaunchAgents/com.hanxiaobo.codex-msu2-display.plist
```

Logs are written to:

- `~/Library/Logs/codex-msu2-display.log`
- `~/Library/Logs/codex-msu2-display.error.log`

## Repository layout

- `codex_msu2_native.py` — stable native-font dashboard used in production.
- `codex_msu2_display.py` — Codex app-server client, serial transport, RGB565
  renderer and recovered framebuffer protocols.
- `probe_msu2_sfr.py` — reads the firmware's SFR descriptor table.
- `test_msu2_glyphs.py` — native glyph and fill-command hardware test.
- `test_codex_msu2_display.py` — dependency-free unit tests.
- `com.hanxiaobo.codex-msu2-display.plist` — macOS LaunchAgent.

## Test

```bash
python3 -m unittest -v
python3 -m py_compile codex_msu2_display.py codex_msu2_native.py
plutil -lint com.hanxiaobo.codex-msu2-display.plist
```

## Safety

Normal display operation writes only volatile LCD RAM and controller state.
The included dashboard does not erase or program the external P25D80 Flash.

## License

MIT
