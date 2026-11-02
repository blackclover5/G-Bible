"""Install the read-aloud voice into .venv, and check it works.

    python3 tools/install_voice.py

The voice is the only thing in this project that is not the standard library, so
it is installed into `.venv/` beside the app rather than vendored into it --
`run.py` re-executes into that venv when it finds one.  See
[Read aloud](../README.md#read-aloud).

Why this is a script and not one line of pip
-------------------------------------------

`pip install onnxruntime kittentts` is the obvious thing and it does not work on
a current Python.  KittenTTS 0.8.1 requires `misaki>=0.9.4`, misaki's own
metadata caps it at `<3.13`, and so on Python 3.13 pip resolves to misaki 0.7.2
and then fails with "no matching distribution".  Two more failures sit behind
it:

* Asking for the whole set at once makes pip fall back to building spacy from
  source, because `--ignore-requires-python` also ignores which wheels exist.
  spacy has 3.13 wheels; blis, its build dependency, does not compile here.
* misaki and phonemizer-fork are pure Python and run perfectly on 3.13.  Only
  their version metadata is stale, so they are installed with
  `--ignore-requires-python` and their dependencies named explicitly instead of
  being resolved.

So: the wheels that do publish 3.13 builds are installed normally, the three
that do not are installed without dependency resolution, and the result is
verified by importing it and asking for the voice's status.  A partially
installed voice fails loudly here rather than as a silent fallback later.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV = ROOT / ".venv"
PY = VENV / "bin" / "python"

KITTEN_WHEEL = ("https://github.com/KittenML/KittenTTS/releases/download/"
                "0.8.1/kittentts-0.8.1-py3-none-any.whl")

#: Installed normally: each of these publishes a wheel for 3.11 through 3.13.
WHEELS = ["numpy", "onnxruntime", "huggingface_hub", "soundfile", "num2words",
          "spacy>=3.8.7", "espeakng_loader", "joblib", "dlinfo", "attrs",
          "segments", "regex", "addict", "Unidecode"]

#: Installed without dependency resolution, because their metadata still caps
#: them below 3.13 although the code runs there.  Each one's dependencies are
#: already named in WHEELS above or come with it.
UNPINNED = ["misaki", "phonemizer-fork"]

#: The last three are pure-Python wheels from a URL, not from an index.
FROM_URL = [KITTEN_WHEEL]


def run(args: list[str], **kw) -> None:
    print("  $", " ".join(args))
    subprocess.run(args, check=True, **kw)


def main() -> int:
    if not PY.is_file():
        print(f"Creating {VENV}")
        venv.EnvBuilder(with_pip=True, clear=False).create(str(VENV))

    print("Installing the voice. This is ~300 MB of wheels; it takes a while.")
    run([str(PY), "-m", "pip", "install", "--upgrade", "pip"], stdout=subprocess.DEVNULL)
    run([str(PY), "-m", "pip", "install", *WHEELS])
    run([str(PY), "-m", "pip", "install", "--ignore-requires-python",
         "--no-deps", *UNPINNED])
    run([str(PY), "-m", "pip", "install", "--ignore-requires-python",
         "--no-deps", *FROM_URL])

    print("\nChecking it can actually speak...")
    # Asked of the venv's own interpreter, not this one: that is the
    # difference the whole installation exists to make.  The project root comes
    # in as argv rather than being interpolated into the source, so there is one
    # less layer of quoting between here and `from gbible import tts`.
    code = textwrap.dedent("""
        import sys
        sys.path.insert(0, sys.argv[1])
        from gbible import tts
        st = tts.status()
        print("voice:", st["voice"], "| available:", st["available"], "|",
              st["reason"] or "ready")
        raw = tts.synthesise("In the beginning was the Word.")
        print("synthesised", len(raw), "bytes of WAV")
        sys.exit(0 if st["available"] else 1)
    """)
    r = subprocess.run([str(PY), "-c", code, str(ROOT)],
                       capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    if r.returncode != 0:
        print("\nThe voice did not come up. The app will fall back to the "
              "browser's speech engine; run this again to try once more.")
        return 1

    print("\nDone. Start the app with:  python3 run.py")
    print("The model itself (~56 MB) downloads on first use.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
