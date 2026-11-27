# Read Aloud

G-Bible can read selected Bible text aloud. Depending on your setup, it uses an installed neural voice or the browser’s speech engine.

## Configure

Open **Settings → Read aloud settings** to select an available voice and adjust playback options. On a source install, the optional voice can be installed with:

```bash
python3 tools/install_voice.py
```

The launcher uses a project `.venv` when present so the voice runtime can be found. Installing the voice requires downloading its runtime/model. Without it, the app may use speech provided by your browser or operating system.

## No sound?

Check the system output device and volume, confirm the browser tab is not muted, then select another voice. On Linux source installs, run the installer above and restart G-Bible. Some browsers do not expose the same voices; behavior can vary by platform.
