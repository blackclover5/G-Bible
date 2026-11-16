"""Optional Rust acceleration layer.

The application remains fully functional without a compiled extension.  When
`gbible._rust_core` is installed, hot-path primitives are dispatched to Rust;
otherwise the established Python implementations remain the reference path.
"""
from __future__ import annotations

try:
    # A top-level extension name lets a source checkout use the wheel-installed
    # native module without extending gbible.__path__ or shadowing Python files.
    import _gbible_rust_core as core  # type: ignore[import-not-found]
except (ImportError, OSError):  # no compiler/build artifact on this machine
    core = None

AVAILABLE = core is not None


def status() -> dict[str, object]:
    return {
        "available": AVAILABLE,
        "engine": "Rust" if AVAILABLE else "Python fallback",
        "features": (["unicode tokenization", "normalization", "stemming",
                      "entity decoding", "whitespace normalization",
                      "positional varints", "spelling distance"] if AVAILABLE else []),
    }
