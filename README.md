# hot_mess_lights

Minimal NiceGUI app for controlling DMX lights with an Enttec DMX USB Pro (via `DMXEnttecPro`).

## Connect

1. Connect to WiFi

    SSID: HotMessLights
    Password: iamahotmess

2. Got to http://192.168.8.100

## Development

From the repo root:

```sh
python -m venv venv          # first time only
source venv/bin/activate
pip install -e .              # editable install, first time only
export HML_DMX_PORT=/dev/tty.usbserial-XXXX   # optional, default selection if nothing is detected
python -m hot_mess_lights     # http://localhost:8080
```

The app scans for USB serial devices on load (Enttec/FTDI devices listed first); pick one from the dropdown, use the refresh button to rescan, then click Connect.

## Run as a systemd service

On a Raspberry Pi 5, use Raspberry Pi OS Bookworm or newer. Bookworm provides Python 3.11 and systemd 252; the app requires Python 3.10 or newer, and the service uses systemd's `AmbientCapabilities` support to bind to port 80. The unit runs the virtual environment's console script, so it uses whichever compatible Python created that environment rather than assuming a hard-coded Python version.

From the repository at `~/HotMessLighting`, create the environment and install the app:

```sh
sudo apt update
sudo apt install python3-venv
python3 --version                 # must be 3.10 or newer
python3 -m venv venv
venv/bin/python -m pip install -e .
```

Install and enable the service for your Linux user:

```sh
sudo cp systemd/hot-mess-lights@.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now "hot-mess-lights@$(whoami).service"
```

The service expects the repository at `/home/<user>/HotMessLighting` and serves on `0.0.0.0:80`. Change `WorkingDirectory`, `ExecStart`, and `HML_DB` in the unit if you use a different installation path. The unit grants only the `CAP_NET_BIND_SERVICE` capability needed to bind port 80. If using a USB DMX interface, add the service user to the `dialout` group (`sudo usermod -aG dialout "$(whoami)"`) and restart the service. Check status and logs with `systemctl status "hot-mess-lights@$(whoami).service"` and `journalctl -u "hot-mess-lights@$(whoami).service"`.

## Usage

- **Setup tab:** connect to the DMX interface and add fixtures. Set a fixture's color with its sliders or color wheel, type a name, and press **Save color** to capture its current output as a palette swatch. Values for all available channels are preserved, including zero dimmer. Use **Capture current preset** to save all fixtures as a static look. Use the pencil on a swatch to edit its name, color and optional channels (unchecked = not set), or the trash icon to delete it.
- **Sequencer tab:** fixtures are listed down the left and steps run across. Pick a palette color as the brush (or the black "Off" swatch) and click cells to paint them. Press Play to loop the sequence; each light crossfades smoothly from one step's color to the next, and the last step fades back to the first. Steps (1-32) and seconds per step are adjustable. Pause playback to use **Capture current swatch** for one fixture or **Capture current preset** for all fixtures, including colors between sequence steps. Use **New preset** to save a static look with an independently selected palette color (or Off) for each fixture; apply, edit, or delete saved looks in the list beside the sequence grid. Selecting a preset stops playback and fades from the current output to the preset over one second. Without a DMX connection it previews on screen only. Stop holds the current light output; use **Blackout** on the Setup tab to turn the lights off.

Swatch channels that aren't set default to off, except Dimmer which defaults to full. Fixtures only receive the channels they have (an RGB Wash uses just R, G, B). Sequence cells and static preset assignments reference palette colors, so deleting one clears its cells and sets matching preset assignments to Off.

Par fixture dimmers initialize to full when added or when connecting the DMX interface. They remain adjustable, and blackout or a sequence/preset can set them to zero.

Captures use the last levels sent by the app, or its previewed levels when disconnected; they do not read back the physical lights. A captured preset reuses matching palette colors and creates named swatches for any other fixture states. Editing or deleting those swatches affects the preset as it does for other palette-based presets. When switching to Setup, sliders show the last tracked levels.

Use **Sync from sequencer** on the Setup tab to update the fixture sliders and color wheels from the current tracked output without changing the lights or saved sequence. If playback is running, this is a snapshot; pause it first to hold the values steady.

Fixtures, palette, sequence and static presets are stored in a SQLite file, `hot_mess_lights.db` in the directory you run from (override with `HML_DB=/path/to/file.db`). It is git-ignored.

**Backup / restore:** at the bottom of the Setup tab, **Download database** saves a timestamped copy of that file through the browser. **Upload database** replaces the current fixtures, colors, sequence and static presets with a previously downloaded file (older files are upgraded automatically; files that aren't valid Hot Mess Lights databases are rejected and nothing changes). The page reloads after a successful upload.

Auto-reload is off (`reload=False` in `hot_mess_lights/__main__.py`), so restart the app after code changes. Set `reload=True` to reload on save; each reload drops the serial connection, so you'll need to click Connect again.

## Packaging

Build a wheel and source distribution:

```sh
source venv/bin/activate
pip install build
python -m build          # outputs to dist/
```

This creates `dist/hot_mess_lights-<version>.whl` and `.tar.gz`. Bump `version` in `pyproject.toml` before releasing.

The GitHub Actions build uses Python 3.13 on 64-bit ARM Linux and uploads the distributions and systemd unit as separate artifacts. The pure-Python wheel is not tied to macOS or Linux.

Install the wheel anywhere (ideally in a fresh virtual environment) and run it:

```sh
python -m venv /path/to/env
/path/to/env/bin/pip install dist/hot_mess_lights-0.1.0-py3-none-any.whl
/path/to/env/bin/hot_mess_lights        # or: python -m hot_mess_lights
```

Dependencies (`nicegui`, `DMXEnttecPro`, `pyserial`) are installed automatically. The app creates `hot_mess_lights.db` in the directory it is run from; set `HML_DB` to choose another location.

To publish to PyPI, upload with `pip install twine && twine upload dist/*`.
