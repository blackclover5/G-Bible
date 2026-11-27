"""Opt-in gating for the AI Assistant.

A fresh G-Bible has no AI: no provider configured and no AI controls in the
interface.  The reader reaches Settings → AI Assistant, enables it and chooses
an external provider (a local Ollama/LM Studio/llama.cpp server, or a cloud
key).  G-Bible downloads no model and bundles no provider.

Everything here is deliberately light: the server asks whether AI is enabled
on every request, so this module must never import a provider or model stack.
"""

from __future__ import annotations

from . import db

#: The flag is a plain setting, not part of the `ai` settings dict: it survives
#: a reset of AI preferences and is the one thing that decides whether the
#: feature exists in the interface at all.
FLAG = "ai_enabled"


def enabled() -> bool:
    return bool(db.get_setting(FLAG, False))


def set_enabled(value: bool) -> bool:
    db.set_setting(FLAG, bool(value))
    return bool(value)


def status() -> dict:
    """The only status the client needs: is the Assistant switched on?"""
    return {"ok": True, "enabled": enabled()}


def start_install(mode: str = "", model: str = "") -> dict:
    """Enable the Assistant.  There is no download and no background job.

    The mode argument is accepted so an older client still works; it is ignored.
    """
    set_enabled(True)
    return {"ok": True, "enabled": True,
            "message": "AI Assistant enabled. Choose a provider below."}


def disable(remove_data: bool = False) -> dict:
    """Hide the Assistant again.  Conversations and keys are left alone."""
    set_enabled(False)
    return {"ok": True, "enabled": False}
