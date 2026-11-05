# hot_mess_lights

Minimal NiceGUI app for controlling DMX lights with an Enttec DMX USB Pro (via `DMXEnttecPro`).

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

## Usage

- **Setup tab:** connect to the DMX interface and add fixtures. Set a fixture's color with its sliders or color wheel, type a name, and press **Save color** to add it to the palette. A swatch is RGB plus optional White, Amber, UV and Dimmer values; when saving from a fixture, only non-zero W/A/U/D values are kept. Use the pencil on a swatch to edit its name, color and optional channels (unchecked = not set), or the trash icon to delete it (which also clears it from the sequencer).
- **Sequencer tab:** fixtures are listed down the left and steps run across. Pick a palette color as the brush (or the black "Off" swatch) and click cells to paint them. Press Play to loop the sequence; each light crossfades smoothly from one step's color to the next, and the last step fades back to the first. Steps (1-32) and seconds per step are adjustable. Without a DMX connection it previews on screen only; Stop blacks out the lights.

Swatch channels that aren't set default to off, except Dimmer which defaults to full. Fixtures only receive the channels they have (an RGB Wash uses just R, G, B). Cells reference palette colors, so deleting one clears its cells.

Fixtures, palette and sequence are stored in a SQLite file, `hot_mess_lights.db` in the directory you run from (override with `HML_DB=/path/to/file.db`). It is git-ignored.

Auto-reload is off (`reload=False` in `hot_mess_lights/__main__.py`), so restart the app after code changes. Set `reload=True` to reload on save; each reload drops the serial connection, so you'll need to click Connect again.
