"""Machine translation of search hits and passages.

There were forty-five APIs registered and every one of them disabled, with no
feature anywhere that used them.  This is that feature: the plumbing was already
there -- a registry, keys, a cache table nothing had written to -- and the
missing part was deciding what to ask a scripture or lexicon API, which is
nothing.  Translation is a different job, so it gets its own providers here
rather than pretending a Bible API can do it.

What is honest about it
-----------------------
* Every provider is named with its limits.  MyMemory is free and needs no key,
  and it is run by volunteers with a public term sheet; a paragraph of patristic
  English may come back unchanged, and the response says `unchanged` rather than
  pretending otherwise.
* Machine translation of scripture is for orientation, not for study.  Every
  response carries that, and the front end shows it above the text rather than
  in a footnote nobody opens.
* Translations are cached in `api_cache` by text and pair.  A search for a
  common word across forty hits costs one request, and re-running the search
  costs nothing.
* Nothing is sent anywhere unless a provider is enabled first.  The registry
  ships everything off, and this keeps that: `enabled` is never set here.

Providers are described by data, not by subclasses, because the only thing that
varies is the URL and how to read the answer out of it.
"""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from . import db
from .api import registry as apireg

CATEGORY = "translate"

#: Shown above every translation, not below it.
DISCLAIMER = ("Machine translation, for orientation only. Check anything you "
              "are going to quote or teach.")

#: Refuse to send a whole book through a translation service by accident.
MAX_CHARS = 4000
MAX_ITEMS = 60

_UA = "GBible/1.0 (local Bible study app)"


def _p(**kw) -> dict:
    """A provider record, with the fields every provider must have.

    Written as data rather than a class because the only thing that varies
    between providers is a URL and how to read the answer out of it.
    """
    kw.setdefault("base_url", "")
    kw.setdefault("site_url", "")
    kw.setdefault("key_required", False)
    kw.setdefault("auth", "none")
    kw.setdefault("key_name", "")
    kw.setdefault("terms_url", "")
    kw.setdefault("license", "")
    kw.setdefault("notes", "")
    kw.setdefault("langs_out", ())
    return kw


PROVIDERS: list[dict] = [
    _p(id="mymemory",
       name="MyMemory",
       vendor="mymemory.translated.net",
       base_url="https://api.mymemory.translated.net",
       site_url="https://mymemory.translated.net/doc/usagelimits.php",
       key_required=False, auth="query", key_name="de",
       category=CATEGORY,
       notes=("Free, no key, run by volunteers. Public term sheet: up to 5,000 "
              "words a day per user, and requests from an unlisted address may "
              "be refused. Quality is uneven on older English."),
       terms_url="https://mymemory.translated.net/doc/usagelimits.php",
       license="Free to use, no redistribution of the service",
       langs_out=("en", "es", "fr", "de", "it", "pt", "nl", "ru", "ar", "he",
                  "hi", "zh-CN", "ja", "ko", "tr", "pl", "sv", "el", "th",
                  "vi", "id", "fi", "cs", "hu", "ro", "uk", "fa", "bn", "ta")),
    _p(id="lingva",
       name="Lingva Translate",
       vendor="lingva.ml (an open-source front end for Google Translate)",
       base_url="https://lingva.ml/api/v1",
       site_url="https://github.com/thedaviddias/lingva",
       key_required=False, auth="none",
       category=CATEGORY,
       notes=("An open-source instance, so there is no account and no key. "
              "Public instances come and go; if this one is down, point the "
              "provider at your own with `base_url`."),
       license="AGPL-3.0 (the service); results are not a licensed work",
       langs_out=("en", "es", "fr", "de", "it", "pt", "nl", "ru", "ar", "he",
                  "fa", "ja", "ko", "zh-CN", "tr", "pl", "uk", "vi", "id")),
]

PROVIDER_BY_ID = {p["id"]: p for p in PROVIDERS}

LANGUAGES = [
    ("en", "English"), ("es", "Spanish"), ("fr", "French"), ("de", "German"),
    ("it", "Italian"), ("pt", "Portuguese"), ("nl", "Dutch"), ("ru", "Russian"),
    ("ar", "Arabic"), ("he", "Hebrew"), ("hi", "Hindi"), ("fa", "Persian"),
    ("zh-CN", "Chinese (simplified)"), ("ja", "Japanese"),
    ("ko", "Korean"), ("tr", "Turkish"), ("pl", "Polish"), ("uk", "Ukrainian"),
    ("vi", "Vietnamese"), ("id", "Indonesian"), ("th", "Thai"),
    ("el", "Greek"), ("cs", "Czech"), ("sv", "Swedish"), ("fi", "Finnish"),
    ("hu", "Hungarian"), ("ro", "Romanian"), ("bn", "Bengali"),
    ("ta", "Tamil"),
]


# ------------------------------------------------------------- registration

def sync() -> int:
    """Add the translation providers to the API table.

    Written straight to the database rather than added to `apireg.APIS`,
    because that list is a catalogue of scripture and lexicon services and this
    is a different kind of thing; `apireg.sync()` rewrites its own rows and
    would not disturb these, but neither should it have to know about them.

    `enabled` is written only on insert, so re-running this cannot switch on a
    provider the user deliberately turned off.
    """
    conn = db.connect()
    n = 0
    for i, p in enumerate(PROVIDERS):
        conn.execute(
            "INSERT INTO api(id,name,vendor,category,base_url,doc_url,site_url,"
            "key_required,auth,key_name,rate_limit,terms_url,license,notes,"
            "enabled,position) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?) "
            "ON CONFLICT(id) DO UPDATE SET name=excluded.name, "
            "vendor=excluded.vendor, category=excluded.category, "
            "base_url=excluded.base_url, doc_url=excluded.doc_url, "
            "site_url=excluded.site_url, key_required=excluded.key_required, "
            "auth=excluded.auth, key_name=excluded.key_name, "
            "terms_url=excluded.terms_url, license=excluded.license, "
            "notes=excluded.notes, position=excluded.position",
            (p["id"], p["name"], p["vendor"], p["category"], p["base_url"],
             "", p["site_url"], int(p["key_required"]), p["auth"],
             p["key_name"], "", p["terms_url"], p["license"], p["notes"],
             900 + i))
        n += 1
    conn.commit()
    return n


def available() -> list[dict]:
    """Providers, with what the user has to do before each one works."""
    conn = db.connect()
    out = []
    for p in PROVIDERS:
        row = conn.execute("SELECT enabled FROM api WHERE id=?",
                           (p["id"],)).fetchone()
        out.append({**{k: p[k] for k in ("id", "name", "vendor", "notes",
                                          "terms_url", "license", "site_url")},
                    "enabled": bool(row["enabled"]) if row else False,
                    "key_set": bool(apireg.key_for(p["id"])),
                    "key_required": p["key_required"],
                    "languages": list(p["langs_out"])})
    return out


def enabled_provider(preferred: str = "") -> str:
    conn = db.connect()
    rows = conn.execute("SELECT id, enabled FROM api WHERE category=? "
                        "ORDER BY position", (CATEGORY,)).fetchall()
    have = {r["id"]: bool(r["enabled"]) for r in rows}
    if preferred and have.get(preferred):
        return preferred
    for p in PROVIDERS:
        if have.get(p["id"]):
            return p["id"]
    return ""


# ------------------------------------------------------------------ caching

def _cache_get(provider: str, key: str) -> dict | None:
    r = db.connect().execute(
        "SELECT payload, fetched FROM api_cache WHERE api_id=? AND kind=? "
        "AND key=?", (provider, "translate", key)).fetchone()
    if not r:
        return None
    try:
        payload = json.loads(r["payload"])
    except (json.JSONDecodeError, TypeError):
        return None
    payload["cached"] = True
    payload["fetched"] = r["fetched"]
    return payload


def _cache_put(provider: str, key: str, payload: dict) -> None:
    db.connect().execute(
        "INSERT OR REPLACE INTO api_cache(api_id,kind,key,payload,fetched) "
        "VALUES(?,?,?,?,?)",
        (provider, "translate", key, json.dumps(payload, ensure_ascii=False),
         time.time()))
    db.connect().commit()


# ----------------------------------------------------------------- requests

def _fetch_mymemory(text: str, src: str, tgt: str, timeout: int) -> dict:
    q = {"q": text[:1200], "langpair": f"{src}|{tgt}"}
    key = apireg.key_for("mymemory")
    if key:
        q["de"] = key              # the optional e-mail, for a higher quota
    url = "https://api.mymemory.translated.net/get?" + urllib.parse.urlencode(q)
    req = urllib.request.Request(url, headers={"User-Agent": _UA,
                                               "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8", "replace"))
    status = data.get("responseStatus")
    text_out = ((data.get("responseData") or {}).get("translatedText") or "").strip()
    out = {"text": text_out, "status": status,
           "matches": len(data.get("matches") or [])}
    if status not in (200, "200", None):
        out["error"] = str(data.get("responseDetails") or
                           f"MyMemory refused the request ({status})")
    elif not text_out:
        out["error"] = "no translation returned"
    return out


def _fetch_lingva(text: str, src: str, tgt: str, timeout: int) -> dict:
    url = (PROVIDER_BY_ID["lingva"]["base_url"] + "/"
           + urllib.parse.quote(tgt) + "/" + urllib.parse.quote(src)
           + "?" + urllib.parse.urlencode({"q": text[:1200]}))
    req = urllib.request.Request(url, headers={"User-Agent": _UA,
                                               "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8", "replace"))
    out = {"text": (data.get("translation") or "").strip(), "status": 200}
    if not out["text"]:
        out["error"] = "no translation returned"
    return out


_FETCH = {"mymemory": _fetch_mymemory, "lingva": _fetch_lingva}


def _one(provider: str, text: str, src: str, tgt: str,
         timeout: int = 20) -> dict:
    body = (text or "").strip()
    if not body:
        return {"text": "", "error": "nothing to translate"}
    if src == tgt:
        return {"text": body, "unchanged": True,
                "note": "source and target are the same language"}
    key = f"{src}>{tgt}:{body}"
    hit = _cache_get(provider, key)
    if hit is not None:
        return hit
    fn = _FETCH.get(provider)
    if fn is None:
        return {"text": "", "error": f"no way to ask {provider}"}
    try:
        out = fn(body, src, tgt, timeout)
    except Exception as e:
        out = {"text": "", "error": f"{PROVIDER_BY_ID[provider]['name']}: {e}"}
    out["source_text"] = body
    if out.get("text") and out["text"].strip() == body:
        # Left untranslated on purpose by the service, or a phrase it copied
        # verbatim.  Say so: a translation panel that silently shows the
        # original is worse than one that admits it has nothing.
        out["unchanged"] = True
        out["note"] = ("the service returned the text unchanged -- usually a "
                       "name, a number, or a passage it has no translation for")
    if out.get("text") and not out.get("error"):
        try:
            _cache_put(provider, key, out)
        except Exception:
            pass
    return out


# -------------------------------------------------------------------- api

def translate(items: list[dict], *, target: str = "es", source: str = "auto",
              provider: str = "", limit: int = MAX_ITEMS) -> dict:
    """Translate a list of `{id, text, label}` records.

    Requests go out together but not all at once: a translation service is a
    volunteer-run public endpoint as often as not, and firing forty requests at
    a wall clock is how you get the whole thing refused.
    """
    prov = enabled_provider(provider)
    if not prov:
        return {"ok": False,
                "error": "No translation service is switched on.",
                "hint": "Open API Settings, find a Translate provider and "
                        "enable it. Nothing is sent anywhere until you do."}
    rows = [i for i in (items or []) if (i.get("text") or "").strip()]
    if not rows:
        return {"ok": False, "error": "nothing to translate"}
    if len(rows) > limit:
        rows = rows[:limit]
    truncated = len(items or []) - len(rows)
    total_chars = sum(len(r["text"]) for r in rows)
    if total_chars > MAX_CHARS:
        return {"ok": False,
                "error": f"that is {total_chars:,} characters; this sends at "
                         f"most {MAX_CHARS:,} at a time",
                "hint": "Translate fewer verses, or a chapter at a time."}

    src = "" if source in ("auto", "") else source
    workers = 4
    out_rows: list[dict] = [None] * len(rows)   # keep the request order
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_one, prov, r["text"], src, target): i
                   for i, r in enumerate(rows)}
        for fut, i in futures.items():
            res = fut.result()
            r = rows[i]
            out_rows[i] = {"id": r.get("id", ""),
                           "label": r.get("label", ""),
                           "source": r.get("text", ""),
                           "text": res.get("text", ""),
                           "error": res.get("error"),
                           "unchanged": bool(res.get("unchanged")),
                           "note": res.get("note", ""),
                           "cached": bool(res.get("cached")),
                           "matches": res.get("matches", 0)}
    failed = [r for r in out_rows if r["error"]]
    return {"ok": True, "provider": prov,
            "provider_name": PROVIDER_BY_ID[prov]["name"],
            "target": target, "source": source, "count": len(out_rows),
            "truncated": max(0, truncated),
            "cached": sum(1 for r in out_rows if r["cached"]),
            "failed": len(failed), "disclaimer": DISCLAIMER,
            "rows": out_rows}


_HELP = {"mymemory": "MyMemory usage limits",
         "lingva": "Lingva Translate"}


def languages(provider: str = "") -> list[dict]:
    """What the chosen provider can actually do."""
    prov = provider or enabled_provider()
    out = [{"code": c, "label": l} for c, l in LANGUAGES]
    if not prov:
        return out
    ok = set(PROVIDER_BY_ID[prov]["langs_out"])
    return [{**o, "supported": o["code"] in ok} for o in out]


def status() -> dict:
    prov = enabled_provider()
    p = PROVIDER_BY_ID.get(prov)
    return {
        "ok": True,
        "enabled": bool(prov),
        "provider": prov,
        "provider_name": p["name"] if p else "",
        "providers": available(),
        "disclaimer": DISCLAIMER,
        "note": ("Every provider ships switched off, as every API in this app "
                 "does. Enabling one is the only thing that lets this app send "
                 "text off this machine."),
        "help": _HELP,
    }