"""Read aloud: Kitten TTS Nano v0.8, on the CPU, on this machine.

This is the one part of the app that needs something installed.  Everywhere else
is the standard library and nothing else, and it is worth saying why that line
was worth moving: reading a Bible aloud out loud is not a convenience, and the
browser's own speech engine is a poor substitute for it.  On Linux it is
whatever speech-dispatcher happens to have, which on a bare system is often
nothing at all, and where it exists it is a robotic voice with no idea what a
verse number is supposed to sound like.  So this speaks the text itself, with a
neural voice, offline, with no API key and no per-character bill.

* Model: `KittenML/kitten-tts-nano-0.8-fp32` -- 15M parameters, ~56 MB, fetched
  once from the Hugging Face hub into the ordinary hub cache
  (`~/.cache/huggingface`) and read from there on every later run.
* Licence: Apache-2.0, for the code and the weights alike, so it can be shipped
  in something you give away.  See ATTRIBUTIONS.md.
* Voice: Bruno, one of eight.  `VOICES` below.

Everything about it is optional.  If `onnxruntime` and `kittentts` are not
installed -- or the model cannot be fetched -- `available()` is False and the
front end quietly falls back to the browser's speech engine, which is what this
used to do and still works.  Nothing here is imported at module scope, so
importing this file on a machine with none of it installed costs nothing.
"""

from __future__ import annotations

import contextlib
import io
import sys
import threading
import wave
from pathlib import Path
import importlib

#: The hub repository holding the weights.  fp32 rather than int8: the int8
#: build is a quarter of the download, but Kitten's own README notes reports of
#: it misbehaving, and a voice that drops out in the middle of a verse is worse
#: than six megabytes of disk.
MODEL = "KittenML/kitten-tts-nano-0.8-fp32"

#: Bruno, the voice this app reads with.
VOICE = "Bruno"

#: All eight voices in the model.  Reported by status() so a caller never has
#: to hard-code the list to change the default.
VOICES = ["Bella", "Jasper", "Luna", "Bruno", "Rosie", "Hugo", "Kiki", "Leo"]

#: The model emits 24 kHz mono; a WAV header has to agree with the samples.
SAMPLE_RATE = 24000

#: Longest single utterance.  The front end sends one verse at a time, so this
#: is a guard rather than a limit on reading -- but a whole chapter arriving as
#: one request would be a few hundred times the work, on one thread, holding a
#: lock, with nothing to show for it until it finished.
MAX_CHARS = 4000

_model = None
_load_lock = threading.Lock()
_gen_lock = threading.Lock()

#: Set once a load has been tried and failed, so a broken install reports one
#: clear reason instead of re-raising a stack trace on every verse.
_error = ""


class Unavailable(Exception):
    """The voice is not installed, or the model could not be loaded."""


@contextlib.contextmanager
def _quiet():
    """Swallow the library's own "Generating audio for text: ..." line.

    It prints once per utterance, which for a chapter read aloud is a couple of
    thousand lines of the whole verse into a server log that is otherwise a
    handful of lines at startup.  There is no logger to turn it off, so stdout
    is pointed at a buffer for the duration.

    The window is process-wide, so a line another thread happens to print during
    it goes the same way.  That is a deliberate trade: it can lose one line of
    unrelated startup output once, where the alternative is permanently losing
    the ability to read the log.
    """
    buf = io.StringIO()
    out = sys.stdout
    sys.stdout = buf
    try:
        yield
    finally:
        sys.stdout = out


def available() -> bool:
    """Is there a working voice behind this?"""
    try:
        return load() is not None
    except Unavailable:
        return False


def status() -> dict:
    """What the front end asks before it offers to read anything.

    `available` is deliberately not a fast answer: it is the difference between
    promising a voice and then not producing one, and the check is cheap once
    the model is warm.  `reason` is what the user is shown, so it is a sentence
    with the fix in it rather than a module name.
    """
    try:
        load()
    except Unavailable as exc:
        return {"available": False, "reason": str(exc), "voice": VOICE,
                "voices": VOICES, "model": MODEL}
    return {"available": True, "voice": VOICE, "voices": VOICES,
            "model": MODEL, "sample_rate": SAMPLE_RATE, "reason": ""}


def warm() -> None:
    """Load the model in the background so the first ▶ is not a 4-second wait.

    Failure is recorded, not raised: the point is that it happens off the
    request path, and `status()` will explain it if it did not work.
    """
    try:
        load()
    except Unavailable:
        pass


def load():
    """The loaded model, or raise Unavailable.

    Loading is a one-off 4-5 seconds and every reader would otherwise pay it:
    the front end fetches one verse at a time, so without this the first click
    would sit silent through a model load and look broken.
    """
    global _model, _error
    if _model is not None:
        return _model
    with _load_lock:
        if _model is not None:
            return _model
        if _error:
            raise Unavailable(_error)
        try:
            # The installer runs after the app is already running.  In that
            # case this process is still using the system interpreter, while
            # the optional voice packages live in the app-local .venv.  Add
            # that environment's matching site-packages path on demand; the
            # installer creates it with this same Python version.  Core app
            # imports remain independent of the voice packages.
            root = Path(__file__).resolve().parents[1]
            venv = root / ".venv"
            if venv.is_dir():
                candidates = list((venv / "lib").glob("python*/site-packages"))
                candidates.extend((venv / "Lib" / "site-packages",))
                for candidate in candidates:
                    if candidate.is_dir() and str(candidate) not in sys.path:
                        sys.path.insert(0, str(candidate))
            importlib.invalidate_caches()
            import numpy  # noqa: F401  (fails here rather than at synthesis)
            from kittentts import KittenTTS
        except ImportError as exc:
            _error = ("the voice is not installed -- "
                      f"pip install onnxruntime kittentts ({exc.name} is missing)")
            raise Unavailable(_error) from exc
        try:
            with _quiet():
                _model = KittenTTS(MODEL)
        except Exception as exc:
            _error = (f"the voice could not be loaded: {type(exc).__name__}: {exc}")
            raise Unavailable(_error) from exc
        return _model


def synthesise(text: str, voice: str = VOICE, speed: float = 1.0) -> bytes:
    """Speak `text`, return a WAV.

    Not soundfile and not scipy: the model hands back a float array and turning
    that into a 16-bit PCM file is about ten lines of the standard library, so
    neither of those has to be installed to read a Bible out loud.
    """
    text = " ".join(str(text or "").split())
    if not text:
        # Not Unavailable: the voice is fine, there was simply nothing to say,
        # and the two are answered differently so the front end knows to fall
        # back to the browser only for the second one.
        raise ValueError("there is nothing to read")
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS]
    if voice not in VOICES:
        voice = VOICE
    try:
        speed = float(speed)
    except (TypeError, ValueError):
        speed = 1.0
    speed = min(2.0, max(0.5, speed))

    # load() before numpy: it is what turns "not installed" into Unavailable,
    # and an import error raised past this point would reach the caller as
    # ModuleNotFoundError instead, which reads as a crash rather than as a
    # machine with no voice on it.
    m = load()
    import numpy as np

    # One model, one lock.  The front end already asks for a verse at a time, so
    # this is close to uncontended -- but it is a shared ONNX session and a
    # second caller must not end up inside it at the same time.
    with _gen_lock:
        with _quiet():
            audio = m.generate(text, voice=voice, speed=speed, clean_text=True)

    pcm = np.clip(np.asarray(audio, dtype=np.float32), -1.0, 1.0)
    pcm = (pcm * 32767.0).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()
