"""AI assistant — Phase 1: remote chat with library-grounded citations.

The design goal is retrieval over generation: the answer is composed from
passages already installed in the local library, every claim is tied to a
numbered source the reader can click, and the assistant declines to invent
material that is not in those sources.  The language model is the reasoning
step over a supplied corpus; it is not the corpus.

Because of that shape the same pipeline serves a local model and a cloud one
without a branch anywhere else in the app:

  * **Local** — an Ollama server on the same machine.  Text never leaves the
    box, which is the whole point for a reader who chose an offline library.
  * **Remote** — OpenAI or Anthropic over HTTPS.  The request body carries the
    retrieved passages and the question; that is the only Bible content that
    travels, and it is the passages *for this question*, not the library.

Privacy follows the codebase's existing rule for credentials (`api-credentials.json`,
kept out of the database so it never rides along in a backup): the API key for
the chosen provider lives in the same file, keyed by `ai-<provider>`, and is
never sent anywhere except to that provider's own endpoint.

`chat` is the first of several things the model is asked to do.  Three more --
**explain**, **summarise** and **translate** a selection -- are wrappers over the
same `stream()` transport, differing only in the instruction prepended to the
text: same provider, same adapter, same SSE endpoint, so a new vendor still
costs a row in `PROVIDERS` and nothing else.  **Smart search** is the odd one
out and is deliberately not conversational: it turns a question into a search
*query* for the reader's own engine, and returns a string rather than an answer,
because the engine's recall is better than the model's and the reader can edit
what it produced.

**Sermon research** (outline, illustration, exposition) is the same machinery
again over a different corpus: the passage the preacher named, its commentary,
its cross-references and the installed sermon works' own points.  It produces
sourced *notes* and refuses to draft the sermon, because the work of preaching
is the preacher's and a paragraph the model wrote is one they would have to
check word by word anyway.

Cloud calls are **metered** (see `record_usage`) so a reader can see what a
month of use has been.  That is the whole reason the local providers matter: a
local model is free and stays free, and the panel that shows the numbers exists
so the difference is visible rather than implied.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from typing import Iterator

from . import db, library, mine, search
from .api import registry as apireg

#: A provider that answers with more than this is not answering a question.
_MAX_BYTES = 12 * 1024 * 1024
_USER_AGENT = "GBible/1.0 (local Bible study app)"


# ==========================================================================
# Providers
# ==========================================================================

class Provider:
    """One place a language model can be reached from.

    `adapter` names the wire format, not the vendor: two vendors that speak the
    OpenAI chat schema share one adapter, so adding one is a row, not a branch.
    `local` is what the UI sorts on — it is the only distinction a reader
    actually makes, "does my text leave this machine".

    `free` is the *second* thing a reader wants to know, and it is not the same
    claim as `local`: a free cloud tier also costs nothing, but the text still
    leaves the machine.  It is shown as a badge and never inferred from the
    price, because a "free" that has to be worked out from a rate-limit page is
    not free, it is homework.

    `free_filter`, when set, narrows a provider's model listing.  OpenRouter is
    why: it answers `/models` with several hundred models of wildly different
    prices, so a list without a filter would put pay-per-token models beside the
    zero-cost ones the reader came for.  It is a predicate over each model's
    decoded JSON object, not a query string, because not every vendor expresses
    "free" the same way.
    """

    def __init__(self, id: str, name: str, adapter: str, base_url: str,
                 local: bool, key_required: bool, key_name: str,
                 doc_url: str = "", models: list[str] | None = None,
                 notes: str = "", free: bool = False,
                 free_filter=None, free_note: str = "",
                 list_without_key: bool = False, start_hint: str = "",
                 embeds: bool = False, embed_path: str = "",
                 embed_model: str = "", embed_batch: int = 32):
        self.id = id
        self.name = name
        self.adapter = adapter          # openai | anthropic | ollama
        self.base_url = base_url.rstrip("/")
        self.local = local
        self.key_required = key_required
        self.key_name = key_name
        self.doc_url = doc_url
        self.models = models or []
        self.notes = notes
        self.free = free
        self.free_filter = free_filter
        self.free_note = free_note
        # Some providers publish their model list without a key.  For those the
        # reader can see what is on offer *before* signing up, which is the
        # whole point of a free tier: the list is the advertisement.
        self.list_without_key = list_without_key
        # What to tell the reader when the server does not answer.  Each local
        # server is started differently, so "is the server running?" is only
        # half an answer -- the other half is which command starts it.
        self.start_hint = start_hint
        # Whether the provider can turn text into a vector.  Not every
        # provider can: Anthropic has no embeddings endpoint, and neither do
        # Groq or OpenRouter, which proxy chat models rather than embedding
        # ones.  A provider that cannot still works -- the retrieval is
        # lexical and the answer is the same, only the ordering of the
        # sources is not improved.
        self.embeds = embeds
        self.embed_path = embed_path
        # The embedding model to ask for.  Empty means "whichever the server
        # has loaded", which is the only answer for a local server that serves
        # one model at a time.
        self.embed_model = embed_model
        # How many texts to put in one request.
        self.embed_batch = embed_batch


def _free_to_use(m: dict) -> bool:
    """OpenRouter: does this model cost nothing to call, and take a question?

    Two separate questions, and both have to be answered yes.

    *Price.* OpenRouter marks a zero-cost model with the `:free` suffix on its
    id -- which the reader also sees and can reason about -- and reports what it
    charges in a `pricing` object.  A model that carries a price is not free
    whatever its name says, so the price is the test and the suffix is only a
    fallback for entries that carry no pricing at all.  A list that promises
    free and bills is worse than a shorter list.

    *Shape.* OpenRouter also lists audio and image models at zero, and a chat
    request to one of those fails.  So a model only qualifies if it answers in
    text.  This is also what lets in `openrouter/free`, the router that picks a
    free model for you: it has no `:free` suffix, and it is the single most
    useful entry on the free list.
    """
    mid = str(m.get("id") or "")
    if not mid:
        return False
    pr = m.get("pricing")
    if not isinstance(pr, dict):
        return mid.endswith(":free")
    try:
        prompt = float(pr.get("prompt") or 0)
        completion = float(pr.get("completion") or 0)
    except (TypeError, ValueError):
        return False
    if prompt or completion:
        return False
    arch = m.get("architecture")
    if isinstance(arch, dict):
        # A model that also emits audio or images is a *generation* model, not a
        # chat model, and a chat request to one of those fails.  OpenRouter
        # spells this as "text+image->text+audio": the part after the arrow is
        # what comes out, and it has to be text alone.
        outs = arch.get("output_modalities")
        if not outs and arch.get("output_modality"):
            outs = [arch.get("output_modality")]
        if isinstance(outs, str):
            outs = [outs]
        if not outs:
            mod = str(arch.get("modality") or "")
            if "->" in mod:
                outs = [p.strip() for p in mod.split("->")[-1].split("+")]
        if outs:
            if any(str(o).strip().lower() != "text" for o in outs):
                return False
    return True


PROVIDERS: list[Provider] = [
    Provider("ollama", "Ollama", "ollama",
             "http://127.0.0.1:11434", True, False, "",
             "https://ollama.com",
             models=["llama3.1", "llama3.2", "mistral", "gemma2", "qwen2.5"],
             start_hint="Is `ollama serve` running?",
             embeds=True, embed_path="/api/embed",
             embed_model="nomic-embed-text", embed_batch=16,
             notes="Runs entirely offline. Start `ollama serve`, pull a model, "
                   "and press Test to list what you have. Nothing is sent "
                   "anywhere."),
    # LM Studio and llama.cpp both expose an OpenAI-compatible server, so they
    # reuse the `openai` adapter for free: only the port differs.  Neither needs
    # a key, and neither can be listed from a preset -- whatever model is loaded
    # is the model there is -- so `models` is empty and the reader presses Test,
    # which asks the server and fills the list in.
    Provider("lmstudio", "LM Studio", "openai",
             "http://127.0.0.1:1234/v1", True, False, "",
             "https://lmstudio.ai", models=[],
             start_hint="In LM Studio, open the Developer tab and Start Server.",
             embeds=True, embed_path="/embeddings", embed_batch=16,
             notes="Runs on this machine. In LM Studio open the Developer tab and "
                   "Start Server, then press Test to list the models it has. "
                   "Nothing is sent anywhere."),
    Provider("llamacpp", "llama.cpp", "openai",
             "http://127.0.0.1:8080/v1", True, False, "",
             "https://github.com/ggml-org/llama.cpp", models=[],
             start_hint="Is `llama-server` running?",
             embeds=True, embed_path="/embeddings", embed_batch=16,
             notes="Runs on this machine. Start `llama-server -m model.gguf` (it "
                   "listens on port 8080 by default), then press Test. Nothing "
                   "is sent anywhere."),
    Provider("openai", "OpenAI", "openai",
             "https://api.openai.com/v1", False, True, "OpenAI API key",
             "https://platform.openai.com/docs",
             models=["gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini"],
             embeds=True, embed_path="/embeddings",
             embed_model="text-embedding-3-small", embed_batch=64,
             notes="Cloud. Sends the passages relevant to your question and your "
                   "question to OpenAI."),
    Provider("anthropic", "Anthropic", "anthropic",
             "https://api.anthropic.com/v1", False, True, "Anthropic API key",
             "https://docs.anthropic.com",
             models=["claude-3-5-sonnet-latest", "claude-3-5-haiku-latest",
                     "claude-3-opus-latest"],
             notes="Cloud. Sends the passages relevant to your question and your "
                   "question to Anthropic."),
    # ---- Free cloud tiers -------------------------------------------------
    # These three have a standing free allowance and need no card, which makes
    # them the honest answer to "is there a free AI I can use".  They are cloud
    # providers in every other respect: the badge says "free", not "private",
    # and the note under the input box still says the text leaves the machine.
    # Two of them are ordinary OpenAI-compatible rows; OpenRouter is the only one
    # that needs code (a model-list filter), because it aggregates hundreds of
    # models of different prices behind one key.
    Provider("groq", "Groq", "openai",
             "https://api.groq.com/openai/v1", False, True, "Groq API key",
             "https://console.groq.com/keys",
             models=["openai/gpt-oss-120b", "openai/gpt-oss-20b",
                     "qwen/qwen3.8-27b"],
             free=True,
             free_note="No card needed. The free allowance is per organisation "
                       "and is roughly 30 requests a minute and 1,000 a day; "
                       "press Test to see what your key actually has.",
             notes="The fastest thing here, and free. Cloud — the passages for "
                   "your question and the question are sent to Groq."),
    Provider("google", "Google AI Studio", "openai",
             "https://generativelanguage.googleapis.com/v1beta/openai", False,
             True, "Google AI Studio API key",
             "https://aistudio.google.com/apikey",
             models=["gemini-3.8-flash", "gemini-3.5-flash-lite",
                     "gemini-3.6-flash"],
             free=True,
             free_note="The free tier is per project and is rate-limited; the "
                       "listed models are the free ones today — press Test to "
                       "see what your key actually has.",
             notes="Free tier on the Flash models, no card, and the largest "
                   "context of any provider here. Cloud — and Google's free tier "
                   "may use what you send to improve their products. Turn the "
                   "library off for anything private."),
    Provider("openrouter", "OpenRouter", "openai",
             "https://openrouter.ai/api/v1", False, True, "OpenRouter API key",
             "https://openrouter.ai/keys",
             models=[], free=True, free_filter=_free_to_use,
             list_without_key=True,
             free_note="Test lists only zero-cost models, and needs no key: "
                       "the list is published. Without a one-off credit "
                       "purchase the free allowance is about 50 requests a day; "
                       "free providers may log prompts.",
             notes="Free tier: one key reaching many models, filtered to the "
                   "zero-cost ones. Cloud — the passages for your question and "
                   "the question are sent to the model's provider."),
]

BY_ID = {p.id: p for p in PROVIDERS}


def get_provider(provider_id: str) -> Provider:
    return BY_ID.get(provider_id) or PROVIDERS[0]


# ==========================================================================
# Settings
# ==========================================================================
# Stored in the `setting` table, not in the credential file, so moving the key
# and moving the *choice* are independent: a reader may switch model without
# re-pasting a key and may re-paste a key without losing their model.

_SETTING_KEY = "ai"


def get_settings() -> dict:
    s = db.get_setting(_SETTING_KEY) or {}
    if not isinstance(s, dict):
        s = {}
    s.setdefault("provider", "ollama")
    s.setdefault("model", "")
    s.setdefault("use_library", True)
    # The reader's own material is on by default, because a reader who has
    # written notes about a passage and asks the assistant about that passage
    # is asking about the notes too.  It is a separate switch from the
    # library's because the two answer different questions, and a reader may
    # well want one without the other.
    s.setdefault("use_mine", True)
    s.setdefault("scope", "")
    s.setdefault("semantic", True)
    s.setdefault("smart_query", True)
    s.setdefault("max_sources", 8)
    return s


def set_settings(**kw) -> dict:
    s = get_settings()
    prev_provider = s["provider"]
    for k in ("provider", "model", "use_library", "use_mine", "scope",
              "semantic", "smart_query", "max_sources"):
        if k in kw and kw[k] is not None:
            s[k] = kw[k]
    p = get_provider(s["provider"])
    if "model" not in kw or kw.get("model") is None:
        # Switching provider: the old provider's model name is meaningless to the
        # new one, and sending "gpt-4o" to Ollama is a 404 the reader cannot
        # explain.  A model named explicitly survives; otherwise fall back.
        if s["provider"] != prev_provider or not s.get("model") \
                or (p.models and s["model"] not in p.models):
            s["model"] = p.models[0] if p.models else ""
    if s.get("max_sources"):
        s["max_sources"] = max(1, min(30, int(s["max_sources"])))
    db.set_setting(_SETTING_KEY, s)
    return s


# ==========================================================================
# Credentials
# ==========================================================================
# The key lives beside the database, in the same 0600 file the other API keys
# use, so the rule `docs/sync.md` states for sync passwords holds here too: a
# database carried to somebody else does not carry the reader's key with it.

def _cred_id(provider_id: str) -> str:
    return f"ai-{provider_id}"


def key_for(provider_id: str) -> str:
    return apireg.key_for(_cred_id(provider_id))


def set_key(provider_id: str, value: str) -> dict:
    return apireg.set_key(_cred_id(provider_id), value)


def has_key(provider_id: str) -> bool:
    return bool(key_for(provider_id).strip())


def providers_view() -> list[dict]:
    """The provider list as the settings UI wants it, with key status."""
    out = []
    for p in PROVIDERS:
        out.append({
            "id": p.id, "name": p.name, "local": p.local,
            "adapter": p.adapter, "base_url": p.base_url,
            "key_required": p.key_required, "key_name": p.key_name,
            "key_set": has_key(p.id) if p.key_required else True,
            "doc_url": p.doc_url, "models": list(p.models), "notes": p.notes,
            "free": p.free, "free_note": p.free_note,
            "embeds": bool(p.embeds), "embed_model": p.embed_model or "",
        })
    return out


# ==========================================================================
# Grounding: build the context from the local library
# ==========================================================================

#: Resource types that are lookup tables or pictures rather than prose.  Kept as
#: ids from `taxonomy`, not reader kinds, because "article" covers both an essay
#: worth quoting and a lexicon headword that is not.
_LOOKUP_TYPES = {
    "Lexicon", "Concordance", "Dictionary", "Glossary", "Grammar",
    "CrossReference", "Lectionary", "Atlas", "Map", "Illustration", "Media",
    "Audio",
}


def _plain_query(q: str) -> str:
    """Reduce a question to something the search engine will accept.

    A reader types a *sentence* here — "what does the Bible say about fear" —
    and the query language would treat "about" as a word to find and the
    sentence as a conjunction requiring all of it.  Stripping the handful of
    interrogative/stop words and letting the engine rank the rest is the same
    "smart normalisation" the search box already does, reduced to the minimum
    here because the model, not the reader, is the caller.
    """
    stop = {
        "what", "who", "whom", "where", "when", "why", "how", "does", "did",
        "do", "the", "a", "an", "is", "are", "was", "were", "be", "been",
        "about", "bible", "say", "says", "tell", "me", "of", "in", "on", "to",
        "for", "and", "or", "can", "could", "would", "should", "i", "you",
    }
    words = [w for w in "".join(c if c.isalnum() or c.isspace() else " "
                                for c in q).split() if w.lower() not in stop]
    return " ".join(words[:12]) or q.strip()


def _own_budget(max_sources: int, library_on: bool) -> int:
    """How many of the source slots the reader's own material may take.

    A third is a working number rather than a principle: enough for the reader
    to see what they have written, without their own notes crowding out the
    commentaries that give those notes something to answer to.  With the
    library off there is nothing to crowd out, so the own material has the
    whole budget -- "what did I think about this?" deserves an answer built
    only out of what the reader thought.
    """
    if not library_on:
        return max(1, max_sources)
    return max(1, max_sources // 3)


# ==========================================================================
# Scope: which part of the library the assistant may read
# ==========================================================================
# The assistant can be restricted to a part of the library: everything, a
# collection, a kind of resource, or a single book.  The same idea here:
# the library is a great deal of material, and a reader asking about one
# commentary does not want the answer drawn from two hundred atlases.
#
# A scope is stored as the reader's *intent* -- "the commentary collection" --
# and not as the list of modules it resolves to.  A resolved list goes stale
# the moment the reader adds a book to a collection, and a scope that quietly
# stops including the book it was named for is worse than no scope at all.

def scope_options() -> list[dict]:
    """The scopes the reader can narrow the library to.

    Only the kinds that are actually installed are offered: a scope of
    "commentaries" on a library with no commentaries is a dead end in the
    picker, and a list of dead ends is a list nobody reads.
    """
    out: list[dict] = [{"id": "", "label": "Everything installed",
                        "group": "", "count": 0}]
    try:
        from . import organise, taxonomy
    except Exception:                                    # noqa: BLE001
        return out
    by_type: dict[str, int] = {}
    for m in library.list_all():
        by_type[m.type] = by_type.get(m.type, 0) + 1
    names = {t.id: t.label for t in taxonomy.TYPES}
    for t in sorted(by_type, key=lambda x: (-by_type[x], x)):
        out.append({"id": "type:" + t, "group": "Kind of resource",
                    "label": f"{names.get(t, t)} ({by_type[t]})",
                    "count": by_type[t]})
    try:
        cols = organise.collections()
    except Exception:                                    # noqa: BLE001
        cols = []
    for c in cols:
        if not c.get("count"):
            continue
        out.append({"id": "collection:" + c["id"], "group": "Collection",
                    "label": f"{c.get('name') or 'Collection'} "
                             f"({c['count']})",
                    "count": c["count"]})
    return out


def scope_modules(scope: str) -> list[str]:
    """The module ids a scope names, or [] for the whole library.

    An empty list means "no scope", not "nothing" -- the two are told apart by
    the scope string itself, because a scope that names a collection with
    nothing in it must read *nothing* rather than read everything.
    """
    scope = (scope or "").strip()
    if not scope:
        return []
    kind, _, value = scope.partition(":")
    if kind == "type":
        return [m.id for m in library.list_all() if m.type == value]
    if kind == "collection":
        try:
            from . import organise
            return list(organise.collection_members(value))
        except Exception:                                # noqa: BLE001
            return []
    if kind == "module":
        return [value] if library.get(value) else []
    return []


#: The passage the reader put in front of the assistant, and the rule that
#: goes with it.  A question like "what does Paul mean by this?" is about a
#: *place*, and the search engine cannot find a place from those words; the
#: passage itself has to be supplied, or the answer is about something else.
_CONTEXT_RULE = (
    "The reader has put a passage in front of them, and their question is "
    "about that passage. Source [1] is it. Focus your answer on it, and "
    "cite [1] when you say something about what it says. The other sources "
    "are context for it, not the subject of the question."
)


def _context_source(context: dict) -> dict:
    """The reader's passage, as the first numbered source.

    It is a source and not a separate block, so that the model can cite it
    and the reader can open it: a passage the answer refers to but cannot be
    checked is the one thing the citation list exists to prevent.
    """
    text = (context.get("text") or "").strip()
    label = (context.get("label") or "").strip() or "the passage"
    return {
        "n": 1,
        "module_id": context.get("module_id") or "",
        "module_name": context.get("module_name") or "the passage you are on",
        "label": label,
        "title": label,
        "type": "Passage",
        "text": text,
        "key": context.get("key") or "",
    }


# ==========================================================================
# Embeddings: the semantic half of the hybrid
# ==========================================================================
# The search engine finds passages by their words.  It is very good at that,
# and it is very good at it because the work is arithmetic -- BM25, proximity,
# coverage -- and arithmetic does not know that "anxious" and "worry" are
# the same thing.
#
# That is the gap this fills, and it is a real one.  A reader asks "how do I
# stop being anxious?" and the lexical engine finds the passages that use the
# word; the passage that answers it is the one that says "do not worry about
# your life".  Embeddings know the two are close, and the search engine does
# not.
#
# **Nothing is indexed.** The vectors are made at the moment of the question,
# for the candidates the search engine already found, and thrown away.  That
# is what makes this affordable: the library holds more than a million units
# and there is no way to embed them all, but there are only ever a few dozen
# candidates and they only need embedding once each.
#
# The cost is a few extra calls per question, and the benefit is that the
# model is handed the passage that answers the question rather than the one
# that repeats its words.  A provider that cannot embed is not a worse
# provider: the retrieval is lexical and the answer is the same, only the
# ordering of the sources is not improved.

#: How many candidates are handed to the semantic pass.  Enough for the
#: reordering to matter, few enough that the embedding calls are a moment.
_CANDIDATES = 48


def embed(provider: Provider, texts: list[str]) -> list[list[float]]:
    """The vectors for a list of texts, in the order they were given.

    One shape covers both servers that answer: OpenAI's `/embeddings` and
    Ollama's `/api/embed` both take `{"input": [...]}` and both send a list
    back -- under the key `data` and under the key `embeddings`
    respectively.  Which one it is is read from the reply, not assumed from
    the adapter.
    """
    if not texts:
        return []
    if not provider.embeds or not provider.embed_path:
        raise AiError(f"{provider.name} cannot turn text into a vector.",
                      hint="The sources are ranked by their words instead.")
    out: list[list[float]] = []
    batch = max(1, provider.embed_batch)
    for i in range(0, len(texts), batch):
        chunk = texts[i:i + batch]
        payload = {"model": provider.embed_model, "input": list(chunk)}
        if not payload["model"]:
            del payload["model"]
        req = _request(provider, provider.embed_path, payload,
                       _auth_headers(provider), 60)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read(_MAX_BYTES)
        except urllib.error.HTTPError as e:
            body = b""
            try:
                body = e.read(_MAX_BYTES)
            except Exception:                            # noqa: BLE001
                pass
            msg = _detail(body) or f"HTTP {e.code}: {e.reason}"
            raise AiError(f"{provider.name}: {msg}", status=e.code) from e
        except urllib.error.URLError as e:
            raise AiError(
                f"Could not reach {provider.name}: {e.reason}",
                hint=(provider.start_hint
                      or "Is the local server running?")) from e
        try:
            d = json.loads(raw.decode("utf-8", "replace"))
        except json.JSONDecodeError as e:
            raise AiError(f"{provider.name} did not answer with JSON.",
                          hint="Is an embedding model loaded?") from e
        out.extend(_read_embeddings(d, len(chunk)))
    return out


def _read_embeddings(d: dict, want: int) -> list[list[float]]:
    """The vectors out of a reply, in the order the texts were sent.

    OpenAI answers with `data`, a list carrying an `index`; Ollama answers
    with `embeddings`, in order.  Both are read, because which one a server
    uses is the server's business and not the caller's.
    """
    items = d.get("data")
    if isinstance(items, list) and items:
        out: list[list[float]] = [None] * want        # type: ignore
        for it in items:
            if not isinstance(it, dict):
                continue
            try:
                i = int(it.get("index") or 0)
            except (TypeError, ValueError):
                i = 0
            vec = it.get("embedding")
            if isinstance(vec, list) and 0 <= i < want:
                try:
                    out[i] = [float(x) for x in vec]
                except (TypeError, ValueError):
                    continue
        if all(v is not None for v in out):
            return out                         # type: ignore
    items = d.get("embeddings")
    if isinstance(items, list) and items:
        out = []
        for vec in items:
            if not isinstance(vec, list):
                continue
            try:
                out.append([float(x) for x in vec])
            except (TypeError, ValueError):
                continue
        if len(out) == want:
            return out
    raise AiError("The provider did not return a vector for every text.",
                  hint="Is an embedding model loaded?")


def _cosine(a: list[float], b: list[float]) -> float:
    """The cosine of the angle between two vectors.

    Written out rather than pulled in: the codebase has no third-party code,
    and this is nine lines of arithmetic that would otherwise be a
    dependency on a numerical library for the sake of a dot product.
    """
    num = 0.0
    da = 0.0
    db = 0.0
    for x, y in zip(a, b):
        num += x * y
        da += x * x
        db += y * y
    if da <= 0.0 or db <= 0.0:
        return 0.0
    return num / ((da ** 0.5) * (db ** 0.5))


def _norm(scores: list[float]) -> list[float]:
    """Scores onto a scale of 0 to 1.

    A BM25 score and a cosine similarity are not on the same scale, and
    adding them raw would mean the larger one decided everything.  Each is
    stretched over its own range first, so the two weigh equally.
    """
    if not scores:
        return []
    lo = min(scores)
    hi = max(scores)
    if hi - lo < 1e-9:
        return [0.5] * len(scores)
    return [(s - lo) / (hi - lo) for s in scores]


def semantic_rerank(provider: Provider, question: str,
                     candidates: list[dict]) -> list[dict]:
    """Re-order the candidates by meaning as well as by words.

    The search engine found them by their words; the model has to choose
    between them, and it chooses by what they *say*.  A passage that says
    "do not worry about your life" answers "how do I stop being anxious"
    better than one that uses the word "anxious" once -- and the lexical
    engine cannot know that, because it has never been told what anxious
    means.

    Never raises.  A provider that cannot embed, a model that is not loaded,
    a network that is down: the candidates come back in the order the search
    engine found them, and the question is answered exactly as before.
    """
    if not provider.embeds or not candidates or len(candidates) < 2:
        return candidates
    texts = [c.get("text") or "" for c in candidates]
    try:
        vecs = embed(provider, [question] + texts)
    except Exception:                                    # noqa: BLE001
        return candidates
    if not vecs or len(vecs) != len(candidates) + 1:
        return candidates
    qv = vecs[0]
    sims = [_cosine(qv, v) for v in vecs[1:]]
    lex = [float(c.get("score") or 0.0) for c in candidates]
    lex_n = _norm(lex)
    sem_n = _norm(sims)
    order = sorted(range(len(candidates)),
                   key=lambda i: (-(0.5 * lex_n[i] + 0.5 * sem_n[i]), i))
    out = []
    for rank, i in enumerate(order):
        c = dict(candidates[i])
        c["semantic"] = round(sims[i], 4)
        c["lexical"] = round(lex[i], 4)
        c["rank"] = rank + 1
        out.append(c)
    return out


# ==========================================================================
# The query the assistant searches with
# ==========================================================================
# The stripped question is a poor search, and the reason is not subtle.
#
# "How do I stop being anxious?" becomes "stop being anxious" -- and "stop"
# and "being" are both *more common in the library* than "anxious" (26,418
# units against 1,081).  So the two words that say nothing about the subject
# dominate the ranking, while being ANDed they destroy the recall: the
# passage that actually answers the question never enters the pool.
#
# The engine cannot know that a text about *worry* is a text about *anxiety*.
# It matches words; it has never been told what the words mean.  The model
# can, and that is the whole of the semantic half: the model supplies the
# meaning, the engine does the arithmetic.
#
# So the assistant asks the model which words a source on the subject would
# use, and searches for those.  The engine's own query language is used, so
# the search can still be precise -- and the plain question is still searched
# as well, so a model that writes a useless query costs the reader nothing.

_GROUNDING_QUERY_SYSTEM = (
    "You turn a reader's question about the Bible into a search of a library "
    "of commentaries, lexicons, dictionaries, topical articles, atlases and "
    "Bible texts. You are given the question. Reply with ONE search query, "
    "in the syntax below, that will find the passages and articles which "
    "answer it.\n"
    "The syntax:\n"
    "- plain words are ANDed: `anxious worry` finds units containing both\n"
    "- OR widens: `anxious OR worried`\n"
    "- \"a quoted phrase\" matches the words together\n"
    "- NEAR, WITHIN n WORDS, BEFORE and AFTER keep words close\n"
    "- `strongs:G2316`, `bible:\"Gen 1:1\"` and `heading:word` go straight "
    "to a place\n"
    "Rules:\n"
    "1. Use the words a source on this subject would actually use, not the "
    "reader's words. A question about being anxious is answered by a text "
    "about worry; a question about overcoming fear, by texts about fear and "
    "courage.\n"
    "2. Drop the scaffolding -- \"how do I\", \"what does the Bible say\", "
    "\"the meaning of\". Those are the question, not the subject.\n"
    "3. Two or three content words joined by AND is usually right. Use OR "
    "when the words are alternatives rather than companions.\n"
    "4. Reply with the query only, on one line. No preamble, no explanation, "
    "no code fence."
)

#: The expansion is cached by question, because a question asked twice -- which
#: is the ordinary way a conversation is used -- should be searched for once.
_QUERY_CACHE: dict[str, str] = {}
_QUERY_CACHE_ORDER: list[str] = []


def grounding_query(question: str, provider: Provider | None = None,
                    model: str = "") -> str:
    """The query to search the library with, for a question in the reader's words.

    Returns "" when the model cannot be reached or writes nothing usable, and
    the caller falls back to the plain question.  Never raises: a retrieval
    that cannot be improved is still a retrieval.
    """
    q = (question or "").strip()
    if not q:
        return ""
    if provider is None:
        return ""
    cached = _QUERY_CACHE.get(q)
    if cached is not None:
        return cached
    try:
        provider, model = resolve(provider.id, model or None)
    except AiError:
        return ""
    msgs = [{"role": "system", "content": _GROUNDING_QUERY_SYSTEM},
            {"role": "user", "content": q}]
    parts: list[str] = []
    stats: dict = {}
    try:
        for delta in stream(msgs, provider, model, stats=stats):
            parts.append(delta)
    except Exception:                                    # noqa: BLE001
        return ""
    record_usage(provider.id, model, "grounding:query", stats)
    query = _clean_query("".join(parts))
    if not query or len(query) > 300:
        return ""
    _QUERY_CACHE[q] = query
    if q not in _QUERY_CACHE_ORDER:
        _QUERY_CACHE_ORDER.append(q)
    while len(_QUERY_CACHE_ORDER) > 40:
        old = _QUERY_CACHE_ORDER.pop(0)
        _QUERY_CACHE.pop(old, None)
    return query


def build_context(question: str, max_sources: int = 8,
                  use_library: bool = True, use_mine: bool = True,
                  scope: str = "", context: dict | None = None,
                  provider: Provider | None = None,
                  semantic: bool = True, smart_query: bool = True,
                  model: str = ""
                  ) -> list[dict]:
    """Retrieve the passages that answer `question`.

    Two corpora, one list.

    The **library** is the published material: the search engine's own recall
    over the reader's installed modules.  That is what the assistant has
    always answered from.

    The reader's **own material** -- the notes they wrote, the passages they
    marked, the excerpts they gathered -- is not in that corpus at all, so it
    is retrieved separately (`gbible/mine.py`) and merged in afterwards.

    The two are kept apart on purpose.  A commentary and a private note are
    different kinds of thing; they answer different questions ("what does the
    Bible say" and "what did *I* write"); and the reader has to be able to
    tell which is which, which is why the own material is marked as theirs
    all the way through to the answer.

    The two share one budget.  The own material is given its share *before*
    the library is searched, so a large library cannot crowd it out: a reader
    who has notes on the subject should see them whatever the commentaries
    have to say.  The library then takes what is left -- which is the whole
    budget when the reader has no notes of their own on the subject, because a
    reserved share that goes unused should not shrink the library's.
    """
    out: list[dict] = []
    share = _own_budget(max_sources, use_library) if use_mine else 0
    own = mine.own_sources(question, limit=share) if use_mine else []
    # The reader's passage counts against the budget like any other source.
    # It is the first one, and the one the answer is about, so it does not
    # push the others out -- it takes its own place among them.
    has_context = bool(context and (context.get("text") or "").strip())
    if use_library:
        out += _library_sources(question,
                                max_sources - len(own) - (1 if has_context else 0),
                                scope, provider=provider, semantic=semantic,
                                smart_query=smart_query, model=model)
    out += own
    if has_context:
        # The passage goes first, and the library's copy of it is dropped:
        # the same text under two numbers is a thing the reader would have to
        # work out for themselves.
        ctext = (context.get("text") or "").strip()
        out = [_context_source(context)] + \
            [s for s in out if (s.get("text") or "").strip() != ctext]
    for i, s in enumerate(out):
        s["n"] = i + 1
    return out


def _library_sources(question: str, max_sources: int,
                     scope: str = "", provider: Provider | None = None,
                     semantic: bool = True, smart_query: bool = True,
                     model: str = "") -> list[dict]:
    """The published passages that bear on `question`, from the search engine.

    The work is done in four steps, and the order matters.

    **Ask.** The model writes the query. The stripped question is a poor
    search -- "how do I stop being anxious?" becomes "stop being anxious",
    and those two scaffolding words are more common in the library than the
    word that names the subject -- and only the model knows that a text about
    *worry* is a text about *anxiety*.  The plain question is searched as well
    when the model's query found too little, so a useless one costs nothing.

    **Find.** The search is deliberately broad (the whole library) and the
    pool is wide: the engine recalls, and it recalls better than the model
    does.  A passage that answers the question without repeating any of its
    words is not in the top few, so a narrow pool would never contain it.

    **Re-order.** If the provider can embed, the pool is ranked by meaning
    as well as by words.  This is the step that moves "how do I stop being
    anxious?" from the passages that use the word to the passage that says
    "do not worry about your life".

    **Trim.** Only now are the diversity rules applied: one commentary may
    contribute a couple of units, three translations of a verse are enough,
    and the rest of the room goes to different voices.  Applying them before
    the re-ordering would throw away candidates the re-ordering might have
    put at the top.
    """
    plain = _plain_query(question)
    if not plain:
        return []
    modules = scope_modules(scope)
    if scope and not modules:
        # A scope that names nothing reads nothing.  Falling back to the whole
        # library here would answer a question the reader deliberately
        # narrowed, which is the one thing the scope exists to prevent.
        return []
    pool = max(max_sources, _CANDIDATES)
    hits: list[dict] = []
    seen: set[tuple] = set()

    def take(q: str) -> int:
        """Search one query and merge its hits in.  Returns how many it found."""
        opts = search.SearchOpts(
            modules=modules,
            limit=pool * 2,              # over-fetch: the trim is generous
            snippets=True, smart=False,  # spelling advice is for humans, not models
            fast=True, context=0,
        )
        try:
            res = search.search(q, opts)
        except Exception:                                # noqa: BLE001
            return 0
        got = res.get("hits", []) if isinstance(res, dict) else []
        for h in got:
            key = (h.get("module_id", ""), h.get("key", ""))
            if key in seen:
                continue
            seen.add(key)
            hits.append(h)
        return len(got)

    # The model's query first, because it is the one that knows the vocabulary
    # of the sources.  The plain question is searched as well only when the
    # model's query found too little to work with -- so a model that writes a
    # useless query costs the reader nothing, and a good one is not diluted
    # by the noise the plain question brings.
    smart = ""
    if smart_query and provider is not None:
        smart = grounding_query(question, provider, model)
    if smart:
        if take(smart) < 12 and smart.lower() != plain.lower():
            # The model's query found too little to work with.  The plain
            # question is searched as well, so a model that wrote a useless
            # query costs the reader nothing.
            take(plain)
    else:
        take(plain)

    # -- find: the candidate pool
    cand: list[dict] = []
    per_module: dict[str, int] = {}
    for h in hits:
        text = (h.get("text") or "").strip()
        if not text:
            continue
        mtype = h.get("module_type", "")
        # A lexicon's "faith" entry is a headword, not a passage about faith,
        # and an atlas entry is a picture with a caption.  Grounding an answer in
        # either is worse than having no source at all, so lookup-shaped
        # resources are left to the tools built for them (Concordance, Word
        # study) and never promoted into the assistant's context.
        if mtype in _LOOKUP_TYPES:
            continue
        # One resource may not fill the whole pool either.  The cap is loose
        # here and strict at the trim: this is about not letting a single
        # commentary be the only candidate, not about the final answer.
        if per_module.get(h.get("module_id", ""), 0) >= 8:
            continue
        per_module[h.get("module_id", "")] = per_module.get(h.get("module_id", ""), 0) + 1
        if len(text) > 1200:
            text = text[:1200].rsplit(" ", 1)[0] + " …"
        cand.append({
            "n": 0,
            "module_id": h.get("module_id", ""),
            "module_name": h.get("module_name", ""),
            "label": h.get("label", "") or h.get("title", ""),
            "title": h.get("title", ""),
            "type": h.get("module_type", ""),
            "text": text,
            "score": float(h.get("score") or 0.0),
        })
        if len(cand) >= pool:
            break
    if not cand:
        return []

    # -- re-order: by meaning as well as by words
    if semantic and provider is not None and provider.embeds:
        cand = semantic_rerank(provider, question, cand)

    # -- trim: the diversity rules, and the budget
    out: list[dict] = []
    per_module = {}
    bible_hits = 0
    for c in cand:
        mtype = c.get("type", "")
        # The library holds a dozen translations of the same verse.  Left alone
        # they fill every slot with the same sentence in different words and no
        # commentary is ever reached; three is enough to show a reading and the
        # rest of the room goes to interpreters.
        if mtype in ("Bible", "StudyBible", "ParallelBible", "OriginalLanguage"):
            if bible_hits >= 3:
                continue
            bible_hits += 1
        # Do not let one commentary swamp the context: a single resource may
        # contribute a couple of units, the rest are different voices.
        if per_module.get(c.get("module_id", ""), 0) >= 2:
            continue
        per_module[c.get("module_id", "")] = per_module.get(c.get("module_id", ""), 0) + 1
        c = {k: v for k, v in c.items() if k != "score"}
        c["n"] = len(out) + 1
        out.append(c)
        if len(out) >= max_sources:
            break
    return out


_SYSTEM = (
    "You are G-Bible's study assistant. You help the reader understand Scripture "
    "using ONLY the library passages and the reader's own material supplied in "
    "the context. Follow these rules:\n"
    "1. Answer from the numbered sources. When you state something, cite its "
    "source with its number in brackets, like [1] or [2][3].\n"
    "2. If the sources do not contain the answer, say plainly that the sources "
    "do not cover it. Do NOT invent facts, verse references, quotations "
    "or scholars' names.\n"
    "3. Prefer the Bible text itself when a source is a commentary; note when a "
    "source is a commentary rather than Scripture.\n"
    "4. Write so a first-time reader can follow. Short paragraphs of two or "
    "three sentences; one idea per sentence; ordinary everyday words instead "
    "of theological shorthand. When a special term first appears, give its "
    "plain-English meaning in the same breath. Never end a sentence with more "
    "than two citations.\n"
    "5. Be concise and clear. No preamble about being an AI.\n"
    "6. You research and explain; you do not write sermons or original essays on "
    "the reader's behalf.\n"
    "7. Some sources are the reader's own material -- notes, journal entries, "
    "highlights and clippings they wrote or marked. That is the reader's own "
    "view, not a published source. Report it as theirs (\"in your note on X you "
    "wrote...\"), never attribute it to an author, and never present it as "
    "what a scholar said. Where the reader's own material and a published "
    "source differ, report both and say which is which."
)


def _grounding_blocks(sources: list[dict],
                      heading: str = "Library sources for this question:"
                      ) -> list[str]:
    """The grounding the model reads, as one or two blocks.

    The reader's own material is a **section of its own**, not a continuation
    of the library's.  A private note and a published commentary are different
    kinds of thing, and a model that read them as one list would quote a note
    as though it were a commentary -- which is exactly the confusion the
    citation list exists to prevent.
    """
    out: list[str] = []
    lib = [s for s in sources if not s.get("own")]
    own = [s for s in sources if s.get("own")]
    if lib:
        block = [heading, ""]
        for s in lib:
            head = s["label"] or s["title"] or s["module_name"]
            block.append(f"[{s['n']}] {s['module_name']} — {head}")
            block.append(s["text"])
            block.append("")
        block.append("Use these sources. Cite them by number.")
        out.append("\n".join(block))
    if own:
        block = ["The reader's own material — their own notes, the passages "
                 "they marked, the excerpts they gathered. These are the "
                 "reader's own words, not a published source:", ""]
        for s in own:
            head = s["label"] or s["title"] or s["module_name"]
            block.append(f"[{s['n']}] {s['module_name']} — {head}")
            block.append(s["text"])
            block.append("")
        block.append("Use these too. Cite them by number, and report them as "
                     "the reader's own.")
        out.append("\n".join(block))
    return out


def build_messages(question: str, history: list[dict] | None,
                   sources: list[dict],
                   context: dict | None = None) -> list[dict]:
    """Assemble the chat messages: system, grounding, short history, question."""
    msgs: list[dict] = [{"role": "system", "content": _SYSTEM}]
    for block in _grounding_blocks(sources):
        msgs.append({"role": "system", "content": block})
    if context and (context.get("text") or "").strip():
        msgs.append({"role": "system", "content": _CONTEXT_RULE})
    for m in (history or [])[-8:]:                     # last 8 turns only
        role = m.get("role")
        if role in ("user", "assistant") and m.get("content"):
            msgs.append({"role": role, "content": str(m["content"])[:4000]})
    msgs.append({"role": "user", "content": question})
    return msgs


# ==========================================================================
# Actions: explain / summarise / translate a selection
# ==========================================================================
# These are not a second pipeline.  Each is one instruction plus the reader's
# text, handed to the same `stream()`, so a local model and a cloud model behave
# the same way and a new provider needs no work.  The three differ in exactly two
# ways that matter: whether the library is allowed to speak (only "explain",
# because a summary of a text and a translation of a text must answer to the text
# alone), and what the instruction says.

#: For tasks where grounding would be a fault, not a help.  "Translate this
#: verse" must not retrieve five other verses and blend them in.
_PLAIN_SYSTEM = (
    "You are G-Bible's study assistant. You work only from the text you are "
    "given in this message. Do not invent facts, references, quotations or "
    "scholars' names, and do not add material from outside the text. No preamble "
    "about being an AI."
)

#: `{target}` is filled from the reader's chosen language for translate only.
_ACTIONS: dict[str, str] = {
    "explain": (
        "Explain the passage the reader selected. Say what it means in its "
        "context and note any key words or cross-references, using the numbered "
        "library sources supplied. Cite them by number in brackets, like [1]. If "
        "the sources do not cover something, say so rather than invent it. Be "
        "concise -- a few short paragraphs, not an essay. Write so a "
        "first-time reader can follow: short paragraphs, one idea per "
        "sentence, ordinary everyday words, and the plain-English meaning of "
        "any special term the first time it appears."
    ),
    "summarize": (
        "Summarise the text the reader selected. State the main point in one or "
        "two sentences, then, if it helps, the shape of the passage as a short "
        "list. Use only what the text itself says. Do not cite other resources "
        "and do not add outside material."
    ),
    "translate": (
        "Translate the text the reader selected into {target}. Preserve the "
        "meaning and the register of the original; do not paraphrase, explain, "
        "transcribe or add notes. Return only the translation."
    ),
}


def action_messages(kind: str, text: str, label: str = "", target: str = "",
                    sources: list[dict] | None = None) -> list[dict]:
    """Assemble the messages for one study action.

    `label` is the reference or heading the reader saw, carried into the prompt
    so "the passage" resolves to something the model can name back.  `sources` is
    only ever non-empty for `explain`; the caller decides that, and it is enforced
    here too so a stray grounding list cannot leak into a translation.
    """
    if kind not in _ACTIONS:
        raise AiError(f"Unknown action: {kind}",
                      hint="Expected explain, summarize or translate.")
    text = (text or "").strip()
    if not text:
        raise AiError("There is nothing selected to work on.",
                      hint="Select some text, or open a passage first.")

    grounding = sources if kind == "explain" else []
    system = _SYSTEM if kind == "explain" else _PLAIN_SYSTEM
    instruction = _ACTIONS[kind].format(target=(target or "English").strip())
    msgs: list[dict] = [{"role": "system", "content": system + "\n\n" + instruction}]
    for block in _grounding_blocks(grounding,
                                   "Library sources for this passage:"):
        msgs.append({"role": "system", "content": block})
    head = f"{label}\n\n" if label else ""
    msgs.append({"role": "user", "content": head + text})
    return msgs


def action_sources(kind: str, text: str, label: str, use_library: bool,
                   max_sources: int, use_mine: bool = True,
                   scope: str = "", provider: Provider | None = None,
                   semantic: bool = True, smart_query: bool = True,
                   model: str = "") -> list[dict]:
    """The grounding a given action is allowed to use.

    Only `explain` is grounded, and only when the reader has not turned both
    corpora off: a summary or a translation must answer to the text alone.
    """
    if kind != "explain":
        return []
    if not use_library and not use_mine:
        return []
    # The reader's own notes *on this passage* are found by the anchor, not by
    # their words.  A note that says "conditional immortality -- see Morris"
    # shares no terms with the verse it was taken on, so a text search will
    # never find it, and the anchor is the only thing that connects the two.
    # This is the one place the own material is found by location rather than
    # by question, and it is the place where the reader most expects to find
    # it.  They are gathered first, so they are counted against the budget
    # rather than added on top of it.
    anchored = mine.anchored_sources(label, limit=3) if (use_mine and label) \
        else []
    # The reference is a poor search query on its own ("Ephesians 2 8 10") and a
    # good heading, so grounding is built from the passage's own words while the
    # label rides along as a heading in `action_messages`.
    sources = build_context(text, max_sources - len(anchored),
                            use_library=use_library, use_mine=use_mine,
                            scope=scope, provider=provider,
                            semantic=semantic)
    have = {s["own"]["id"] for s in sources if s.get("own")}
    for c in anchored:
        if c["own"]["id"] in have:
            continue
        sources.append(c)
    for i, s in enumerate(sources):
        s["n"] = i + 1
    return sources


# ==========================================================================
# Smart search: a question in, a query for our own engine out
# ==========================================================================

#: The engine's operators, quoted to the model so it aims at what the engine can
#: actually do rather than at a general web-search syntax it half-remembers.
_SMART_SYSTEM = (
    "You turn a reader's plain-English question into ONE search query for "
    "G-Bible's search engine. The engine understands these operators: AND, OR, "
    "NOT, NEAR, WITHIN n WORDS, BEFORE, AFTER, EQUALS, IN, INTERSECTS, a "
    "\"quoted phrase\", wild*, strongs:G2316, heading:word, bible:\"Gen 1:1\". "
    "Prefer a few good search terms joined with AND over a long query, and use "
    "\"quoted phrases\" for multi-word ideas. Reply with ONLY the query on one "
    "line -- no explanation, no surrounding quotes, no code fence."
)


def _clean_query(raw: str) -> str:
    """Reduce a model's reply to a bare query string.

    Models like to answer with a code fence, a `Query:` label or a trailing
    period even when told not to.  Each is stripped rather than passed on: the
    value goes into the search box and is then run, so a stray backtick is not a
    cosmetic problem, it is a search for a backtick.
    """
    s = (raw or "").strip()
    if s.startswith("```"):
        s = s.strip("`").strip()
        # Drop a language tag on the fence line ("text", "bash") if there is one.
        first, _, rest = s.partition("\n")
        if rest and " " not in first and len(first) <= 12:
            s = rest.strip()
    lines = [ln.strip() for ln in s.splitlines() if ln.strip()]
    s = lines[0] if lines else ""
    for label in ("Query:", "query:", "Search:", "search:"):
        if s.startswith(label):
            s = s[len(label):].strip()
    s = s.strip().strip("`").strip()
    # A model that wrapped the whole query in quotes meant the phrase operator,
    # so the quotes are kept -- but one that wrapped a multi-term query in them is
    # describing it, and quoting it would break the ANDs it wrote.
    if s.count('"') % 2:
        s = s.replace('"', "")
    return s.strip()


def smart_search(question: str, provider_id: str | None = None,
                 model: str | None = None) -> dict:
    """Turn a natural-language question into a query for the search engine."""
    question = (question or "").strip()
    if not question:
        raise AiError("Ask a question for Smart Search to translate.")
    provider, model = resolve(provider_id, model)
    msgs = [{"role": "system", "content": _SMART_SYSTEM},
            {"role": "user", "content": question}]
    stats: dict = {}
    parts = [d for d in stream(msgs, provider, model, stats=stats)]
    query = _clean_query("".join(parts))
    record_usage(provider.id, model, "smart-search", stats)
    if not query:
        raise AiError("The model did not produce a search query.",
                      hint="Try rephrasing the question.")
    return {"ok": True, "query": query, "question": question,
            "provider": provider.id, "model": model}


# ==========================================================================
# The fact book: the assistant, and the lens
# ==========================================================================
# The topic guide's "Questions to Ask" live alongside the lens: the questions
# it suggests take account of the lens the reader is studying the term through.
# This is the same feature, with the lens doing the work it does there.
#
# The topic guide and the fact book are two doors onto one gathering, and
# the assistant reads whatever the door was opened for.  The fact book's
# corpus is the guide's own material -- the name, the place, the article, and
# the verses, glosses, maps and concordance that came with the merge.

#: How many units of each kind the fact book's grounding may hold.  The
#: article comes first because it is what the reader came for; the verses
#: come next because they are what the term is about in Scripture; the
#: glosses come last, because they are concise but shallow.  The three are
#: balanced so that none of them is squeezed out by the cap.
_FACT_LIMITS = {"article": 4, "verses": 5, "dictionary": 3, "atlas": 2,
                "name": 2, "place": 2, "concordance": 2}

#: The lens, and what the reader is asking of the term through it.
_FACT_LENSES = {
    "theological": ("Theological lens",
                    "what the term means for doctrine"),
    "counseling": ("Counseling lens",
                   "what the term means for people in need of it"),
}

#: The overview each lens asks for.  The lens is not a filter on the
#: material -- it is the question the reader is asking of it, and the
#: overview answers that question.
_FACT_OVERVIEW = {
    "": ("Give me an overview of this term from the sources: what it is, "
         "what the passages show about it, and where the sources disagree "
         "or fall short."),
    "theological": ("Give me an overview of this term through the "
                    "theological lens: what it means for doctrine, what the "
                    "passages show about it, and where the sources disagree "
                    "or fall short."),
    "counseling": ("Give me an overview of this term through the counseling "
                   "lens: what it means for people, what the passages show "
                   "about it, and where the sources disagree or fall short."),
}

#: The questions, and the one-line answer under each.
_FACT_QUESTIONS_SYSTEM = (
    "You write the questions a reader would want to ask about a term. You "
    "are given the material on that term. Write four questions the reader "
    "could ask about it, each of them answerable from the material you are "
    "given.\n"
    "Rules:\n"
    "1. Ask about what is actually here -- a claim a source makes, a term it "
    "uses, a tension between them -- and not about the subject in general.\n"
    "2. Do not ask what the sources say about the term. That is too broad to "
    "answer. Ask something narrower, that a reader could get a real answer "
    "to.\n"
    "3. Ask about the sources, not about the reader. No question about what "
    "the reader should believe or do.\n"
    "4. Under each question write ONE line answering it, in a single "
    "sentence, taken from the material you are given. That line is a summary "
    "the reader can read without clicking; the full answer with its "
    "citations comes when they do.\n"
    "5. Reply with the four questions only, numbered 1 to 4, each with its "
    "answer on the line under it, and nothing else. No preamble, no "
    "explanation, no code fence."
)


def fact_sources(term: str, lens: str = "", guide: dict | None = None,
                 max_sources: int = 12) -> list[dict]:
    """The grounding for the fact book: the guide's own material.

    Gathered here rather than handed in by the browser, because what the model
    reads has to be what the *server* holds -- not what the client says it
    holds.
    """
    term = (term or "").strip()
    if not term:
        raise AiError("No term given.", hint="Open a fact book first.")
    if guide is None:
        try:
            from . import study
            guide = study.fact_guide(term, lens=lens) or {}
        except Exception as e:                            # noqa: BLE001
            raise AiError(f"Could not gather the fact book for {term!r}.",
                          hint=str(e) or "Try another term.") from e
    if not guide.get("ok"):
        raise AiError(guide.get("error") or f"Cannot read {term!r}.",
                      hint="Try another term.")
    sections = guide.get("sections") or []
    if not sections:
        raise AiError(f"Nothing installed covers {term}.",
                      hint="Install a fact book, or try another term.")

    out: list[dict] = []

    def add(module_id: str, module_name: str, label: str, title: str,
            mtype: str, text: str, key: str = "") -> bool:
        text = (text or "").strip()
        if not text or len(out) >= max_sources:
            return False
        if len(text) > 1200:
            text = text[:1200].rsplit(" ", 1)[0] + " …"
        out.append({"n": len(out) + 1, "module_id": module_id,
                    "module_name": module_name, "label": label,
                    "title": title, "type": mtype, "text": text, "key": key})
        return True

    for sec in sections:
        kind = sec.get("kind", "")
        if kind not in _FACT_LIMITS:
            continue
        left = _FACT_LIMITS[kind]
        for it in sec.get("items") or []:
            if left <= 0 or len(out) >= max_sources:
                break
            if kind == "verses":
                ok = add(it.get("module_id", ""), it.get("module", ""),
                         it.get("label", ""), it.get("title", ""), "Bible",
                         it.get("text", ""), it.get("key", ""))
            else:
                ok = add(it.get("module_id", ""), it.get("module", ""),
                         it.get("title", "") or it.get("key", ""),
                         it.get("title", ""),
                         "FactBook" if kind in ("article", "name", "place")
                         else ("Dictionary" if kind == "dictionary" else kind),
                         it.get("text", ""), it.get("key", ""))
            if ok:
                left -= 1
    if not out:
        raise AiError(f"Nothing installed covers {term}.",
                      hint="Install a fact book, or try another term.")
    return out


def fact_messages(term: str, question: str, sources: list[dict],
                  lens: str = "") -> list[dict]:
    """The messages for one question about a term.

    The shape is the same as every other call -- a system rule, the numbered
    sources, the question -- so the citation list the reader clicks and the
    sources the model read are built from one list and cannot drift apart.
    """
    term = (term or "").strip()
    lens = (lens or "").strip()
    msgs: list[dict] = [{"role": "system", "content": _FACT_SYSTEM}]
    if lens in _FACT_LENSES:
        label, asks = _FACT_LENSES[lens]
        msgs.append({"role": "system", "content":
                     f"The reader is studying this through the {label}: "
                     f"{asks}. Answer the question from that point of view."})
    if sources:
        block = ["Material on this term:", ""]
        for s in sources:
            title = s["label"] or s["title"] or s["module_name"]
            block.append(f"[{s['n']}] {s['module_name']} — {title}")
            block.append(s["text"])
            block.append("")
        block.append("Work from these. Cite them by number.")
        msgs.append({"role": "system", "content": "\n".join(block)})
    msgs.append({"role": "user", "content": f"Term: {term}\n\n{question}"})
    return msgs


_FACT_SYSTEM = (
    "You are G-Bible's study assistant. You help the reader understand a term "
    "using ONLY the material supplied in the context. Follow these rules:\n"
    "1. Answer from the numbered sources. When you state something, cite its "
    "source with its number in brackets, like [1] or [2][3].\n"
    "2. If the sources do not contain the answer, say plainly that the "
    "sources do not cover it. Do NOT invent facts, verse references, "
    "quotations or scholars' names.\n"
    "3. Prefer the Bible text itself when a source is a commentary; note when "
    "a source is a commentary rather than Scripture.\n"
    "4. Write the same way: short paragraphs, one idea per sentence, ordinary "
    "words, and a term's plain-English meaning the first time it appears.\n"
    "5. Be concise and clear. No preamble about being an AI.\n"
    "6. Where the sources disagree, say that they disagree rather than "
    "choosing one."
)


def _parse_qa(raw: str, limit: int = 4) -> list[dict]:
    """The questions and their one-line answers, out of a model's reply.

    The format asked for is a numbered question with the answer on the line
    under it.  It matters that a half-broken reply still gives the reader
    something to click, so a question with no answer under it is kept: the
    question is the point, and the answer is a convenience.
    """
    out: list[dict] = []
    cur: dict | None = None
    for line in (raw or "").splitlines():
        s = line.strip()
        if not s or s.startswith("```"):
            continue
        head = re.match(r"^\d+[.)]\s*(.*)$", s)
        if head:
            q = head.group(1).strip().strip("\"'\u201c\u201d\u2018\u2019 ")
            cur = {"question": q, "answer": ""} if q else None
            if cur:
                out.append(cur)
                if len(out) >= limit:
                    break
            continue
        # A continuation line is the answer to the question above it.
        if cur is not None and not cur["answer"]:
            cur["answer"] = s.strip().strip("\"'\u201c\u201d\u2018\u2019 ")
            cur = None
    return [q for q in out if q["question"].endswith("?")]


def fact_fallback_questions(guide: dict | None = None) -> list[dict]:
    """The questions the fact book offers when the model cannot be reached.

    The curated set the fact book has always had, which is chosen from what
    the guide actually found rather than written from the text -- so a
    question never promises an answer the material does not hold.
    """
    out: list[dict] = []
    for q in (guide or {}).get("questions") or []:
        out.append({"question": q, "answer": ""})
    return out


def fact_questions(term: str, lens: str = "", provider_id: str | None = None,
                   model: str | None = None,
                   max_sources: int | None = None) -> dict:
    """The questions the fact book should offer, and a one-line answer each.

    Never raises: a model that cannot be reached costs the reader their
    suggested questions and nothing else, and the fact book has a set that
    always works.
    """
    term = (term or "").strip()
    lens = (lens or "").strip()
    fallback: list[dict] = []
    try:
        from . import study
        guide = study.fact_guide(term, lens=lens) or {}
    except Exception:                                    # noqa: BLE001
        guide = {}
    fallback = fact_fallback_questions(guide)
    if not term or not guide.get("ok"):
        return {"ok": True, "questions": fallback, "provider": "",
                "model": "", "fallback": True}
    try:
        provider, model = resolve(provider_id, model)
        sources = fact_sources(term, lens, guide,
                               max_sources=max_sources or 12)
    except Exception:                                    # noqa: BLE001
        return {"ok": True, "questions": fallback, "provider": "",
                "model": "", "fallback": True}
    block = ["Material on this term:", ""]
    for s in sources:
        title = s["label"] or s["title"] or s["module_name"]
        block.append(f"[{s['n']}] {s['module_name']} — {title}")
        block.append(s["text"])
        block.append("")
    system = _FACT_QUESTIONS_SYSTEM
    if lens in _FACT_LENSES:
        label, asks = _FACT_LENSES[lens]
        system += ("\n\nThe reader is studying this through the "
                   f"{label}: {asks}. Ask about that.")
    msgs = [
        {"role": "system", "content": system},
        {"role": "system", "content": "\n".join(block)},
        {"role": "user", "content": f"Term: {term}\n\nWrite the four "
                                    "questions and their answers."},
    ]
    parts: list[str] = []
    stats: dict = {}
    try:
        for delta in stream(msgs, provider, model, stats=stats):
            parts.append(delta)
    except Exception:                                    # noqa: BLE001
        return {"ok": True, "questions": fallback, "provider": provider.id,
                "model": model, "fallback": True}
    record_usage(provider.id, model, "fact:questions", stats)
    questions = _parse_qa("".join(parts))
    if not questions:
        return {"ok": True, "questions": fallback, "provider": provider.id,
                "model": model, "fallback": True}
    return {"ok": True, "questions": questions, "provider": provider.id,
            "model": model, "lens": lens}


def run_fact(term: str, question: str, lens: str = "",
             provider_id: str | None = None, model: str | None = None,
             max_sources: int | None = None) -> dict:
    """Full (non-streaming) answer to one question about a term."""
    provider, model = resolve(provider_id, model)
    sources = fact_sources(term, lens, max_sources=max_sources or 12)
    msgs = fact_messages(term, question, sources, lens)
    parts: list[str] = []
    stats: dict = {}
    for delta in stream(msgs, provider, model, stats=stats):
        parts.append(delta)
    record_usage(provider.id, model, "fact:ask", stats)
    return {
        "ok": True, "answer": "".join(parts), "action": "fact",
        "term": term, "lens": lens, "provider": provider.id,
        "model": model, "citations": sources,
    }


# ==========================================================================
# Which words of a source backed a claim
# ==========================================================================
# The model cites a source, not a location inside it, so the words that
# carried the claim are somewhere in the passage and nowhere marked.  Footnotes
# mark them: hovering a footnote shows the passage with the exact fragment
# the answer leaned on.
#
# They are found here rather than asked of the model.  Asking would mean the
# model reproducing the source's words, and a model that misquotes a source is
# a worse failure than one that cites it loosely -- the whole citation design
# is there so that a claim can be checked against the passage rather than
# taken on trust.
#
# So the two texts are compared: the sentence of the answer around the
# citation marker, and the sentences of the source.  The source sentence that
# shares the most content words with the answer sentence is the fragment.
#
# It is an approximation.  The model may be paraphrasing rather than quoting,
# and then the closest sentence is the closest, not the exact one.  But it is
# an honest one, computed from the two texts.

#: Abbreviations after which a full stop is not the end of a sentence.
_ABBREV = {
    "e.g", "i.e", "cf", "vs", "etc", "no", "fig", "ed", "vol", "ch", "pp",
    "rev", "trans", "orig", "cf.", "seq",
}


def _sentences(text: str) -> list[str]:
    """Split prose into sentences.

    A full stop is a boundary only when what follows starts a new sentence,
    and never after an abbreviation or before a reference: "e.g." is not the
    end of anything, and "Rom. 5:7" is a place, not a stop.
    """
    t = " ".join((text or "").split())
    if not t:
        return []
    out: list[str] = []
    start = 0
    for m in re.finditer(r'[.!?]["\')\]]*\s+', t):
        end = m.end()
        chunk = t[start:end].strip()
        if not chunk:
            continue
        last = re.split(r"[\s(]", chunk)[-1].lower().rstrip(".!?'\")]")
        if last in _ABBREV:
            continue
        if t[end:end + 1].isdigit():
            continue
        out.append(chunk)
        start = end
    tail = t[start:].strip()
    if tail:
        out.append(tail)
    return out


def _content_words(text: str) -> dict[str, list[tuple[int, int]]]:
    """The content words of a text, folded and stemmed, with where they are.

    The offsets are what the highlight is drawn from, so they have to be the
    offsets in *this* text and not in a copy of it.
    """
    out: dict[str, list[tuple[int, int]]] = {}
    for w, start, end in db.words(text):
        if w.lower() in db.STOP_WORDS or len(w) < 3:
            continue
        key = db.token_key(w)
        if not key:
            continue
        out.setdefault(key, []).append((start, end))
    return out


def _fragment(answer_sentence: str, source: str) -> dict | None:
    """The sentence of the source that says what the answer sentence says.

    Returns the sentence and the character ranges of the words the two share,
    so the interface can mark them.
    """
    if not answer_sentence or not source:
        return None
    want = _content_words(answer_sentence)
    if not want:
        return None
    best: dict | None = None
    best_score = 0
    for sentence in _sentences(source):
        have = _content_words(sentence)
        if not have:
            continue
        shared = [k for k in want if k in have]
        # One word in common is a coincidence often enough.  Two is a
        # resemblance, and a sentence with only one content word has to be
        # allowed to match on one.
        if len(shared) < min(2, len(want)):
            continue
        if len(shared) > best_score:
            best_score = len(shared)
            marks: list[list[int]] = []
            for k in shared:
                for start, end in have[k]:
                    marks.append([start, end])
            best = {"text": sentence, "marks": sorted(marks),
                    "score": len(shared)}
    return best


def fragments(answer: str, cites: list[dict]) -> list[dict]:
    """The fragment of each source an answer leaned on.

    `cites` are the citation records -- the ones with `n`, `label` and
    `text`.  The answer is the text the model wrote, with its `[n]` markers
    still in it.
    """
    by_n = {c.get("n"): c for c in (cites or []) if c.get("n")}
    if not by_n:
        return []
    # The answer, split into the sentences the markers sit in.
    marked = re.split(r"(\[\d+\])", answer or "")
    out: list[dict] = []
    for i, piece in enumerate(marked):
        m = re.match(r"^\[(\d+)\]$", piece)
        if not m:
            continue
        n = int(m.group(1))
        cite = by_n.get(n)
        if not cite:
            continue
        # The sentence is this marker and the words around it, up to the
        # next marker.
        before = ""
        for j in range(i - 1, -1, -1):
            if marked[j].startswith("["):
                break
            before = marked[j] + " " + before
        after = ""
        for j in range(i + 1, len(marked)):
            if marked[j].startswith("["):
                break
            after += marked[j]
        sentence = (before + " " + after).strip()
        frag = _fragment(sentence, cite.get("text") or "")
        if not frag:
            continue
        out.append({"n": n, "fragment": frag["text"], "marks": frag["marks"],
                    "label": cite.get("label") or "",
                    "module_name": cite.get("module_name") or ""})
    return out


# ==========================================================================
# Sermon research: outline, illustration and exposition material, cited
# ==========================================================================
# The rule that governs the assistant everywhere governs this hardest.  A sermon
# assistant that drafted the sermon would be the wrong tool twice over: the work
# of preaching is the preacher's, and a paragraph the model wrote is a paragraph
# they have to check word by word anyway, which is slower than writing it.  What
# is actually slow is the *research* -- which points the sources really make,
# where two of them disagree, what an illustration has been used for before.
# So every kind below yields short, sourced notes and nothing else, and the
# instruction says so in as many words, because a model told only "help with my
# sermon" will write one.

#: Prepended to every kind.  Named separately from the kind instruction because
#: it is the promise the feature is built on, not one line of a prompt.
_SERMON_RULE = (
    "You prepare research notes for a preacher who is writing their own sermon. "
    "You do NOT write the sermon: no introduction, no conclusion, no preaching "
    "paragraphs, no prayers, no devotional prose, and no illustration retold in "
    "your own words. Work only from the numbered sources supplied. Never invent "
    "a quotation, a scholar, a story, a statistic or a reference."
)

SERMON_ACTIONS: dict[str, str] = {
    "outline": (
        "From the numbered sources, list possible outline points for a sermon on "
        "this passage. Each point is a short heading -- under twelve words, never "
        "a sentence of prose -- followed by the source number(s) it rests on, in "
        "parentheses, like (2) or (1)(4). Offer three to six points. Where the "
        "sources suggest different structures, show both and say that they "
        "differ. Do not write the sermon those points would become."
    ),
    "illustration": (
        "From the numbered sources, find illustrations for a sermon on this "
        "passage: a story a source tells, a worked example, a quotation, a piece "
        "of historical or cultural background. For each, name in one line what it "
        "illustrates and cite the source number. If the sources hold no "
        "illustration, say so plainly rather than offering something merely "
        "adjacent to the passage."
    ),
    "exposition": (
        "List the observations a preacher should notice in this passage before "
        "preaching it: its structure, words that repeat, key terms, the setting in "
        "the wider book, and cross-references worth following. Short lines, each "
        "cited to its source number. Observations only -- not an exposition, and "
        "not paragraphs."
    ),
}


def sermon_messages(kind: str, ref: str, theme: str = "",
                    sources: list[dict] | None = None) -> list[dict]:
    """Assemble the messages for one piece of sermon research.

    Same shape as `action_messages`: the grounding block is identical in form so
    the citation list the reader clicks and the sources the model read are built
    from one list and cannot drift apart.
    """
    if kind not in SERMON_ACTIONS:
        raise AiError(f"Unknown sermon research: {kind}",
                      hint="Expected outline, illustration or exposition.")
    ref = (ref or "").strip()
    if not ref:
        raise AiError("Give the passage first.",
                      hint="Type a reference like John 3:16 or Romans 8:1-11.")
    head = f"Passage: {ref}"
    if (theme or "").strip():
        head += f"\nSubject the preacher has in mind: {theme.strip()}"
    msgs: list[dict] = [{"role": "system",
                         "content": _SERMON_RULE + "\n\n" + SERMON_ACTIONS[kind]}]
    if sources:
        block = ["Numbered sources:", ""]
        for s in sources:
            title = s["label"] or s["title"] or s["module_name"]
            block.append(f"[{s['n']}] {s['module_name']} — {title}")
            block.append(s["text"])
            block.append("")
        block.append("Work from these. Cite them by number.")
        msgs.append({"role": "system", "content": "\n".join(block)})
    msgs.append({"role": "user", "content": head})
    return msgs


def sermon_sources(ref: str, theme: str = "", use_library: bool = True,
                   max_sources: int = 10) -> list[dict]:
    """Assemble the research corpus for a passage.

    Not a search, deliberately.  The preacher named a *place*, so the corpus is
    that place: its text, the commentary on it, its cross-references, the people,
    places and names in it, and the installed sermon works that mention it --
    whose own points are the raw material an outline is actually made of.  Search
    only comes in when the preacher names a subject, because that is a question
    rather than a location.

    The passage text itself is not optional: a model asked to outline a passage
    it has not been given will confidently outline one it invents, so a reference
    with nothing behind it raises instead.
    """
    out: list[dict] = []

    def add(module_id: str, module_name: str, label: str, title: str,
            mtype: str, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        if len(text) > 1200:
            text = text[:1200].rsplit(" ", 1)[0] + " …"
        out.append({"n": len(out) + 1, "module_id": module_id,
                    "module_name": module_name, "label": label, "title": title,
                    "type": mtype, "text": text})

    try:
        from . import study
        guide = study.passage_guide(ref) or {}
    except Exception as e:                               # noqa: BLE001
        raise AiError(f"Could not read {ref!r} as a passage.",
                      hint=str(e) or "Type a reference like John 3:16.") from e
    if not guide.get("ok"):
        raise AiError(guide.get("error") or f"Cannot read {ref!r} as a passage.",
                      hint="Type a reference like John 3:16 or Romans 8:1-11.")
    label = guide.get("ref") or ref
    for t in guide.get("texts") or []:
        add(t.get("module_id", ""), t.get("module", ""), label, "the passage",
            "Bible", t.get("text", ""))
    if not out:
        raise AiError(f"No Bible in the library covers {ref}.",
                      hint="Check the reference, and that a Bible is installed.")

    if use_library:
        for c in (guide.get("commentary") or []):
            add(c.get("module_id", ""), c.get("module", ""),
                c.get("title", ""), "commentary", "Commentary", c.get("text", ""))

        # Names and places fold into one source: both are short glosses, and two
        # sources of one line each would spend citation numbers on nothing.
        facts: list[str] = []
        for p in (guide.get("people") or [])[:10]:
            n = p.get("name") or ""
            d = p.get("father") or ""
            if n:
                facts.append(f"{n} ({d})" if d else n)
        for n in (guide.get("named") or [])[:10]:
            w, g = n.get("word") or "", (n.get("gloss") or "").strip()
            if w:
                facts.append(f"{w}: {g}" if g else w)
        for p in (guide.get("places") or [])[:10]:
            n, c = p.get("name") or "", (p.get("comment") or "").strip()
            if n:
                facts.append(f"{n}: {c}" if c else n)
        if facts:
            add("", "installed index", "people, places and names", "facts",
                "Facts", "\n".join(facts))

        xr = [x.get("label") or x.get("key") or ""
              for x in (guide.get("xrefs") or [])][:20]
        xr = [x for x in xr if x]
        if xr:
            add("", "cross-reference index", "cross-references",
                "cross-references", "CrossReference", ", ".join(xr))

        # The installed sermon works' own points.  This is the material an
        # outline is made from, and it arrives already extracted by `preach`
        # rather than re-derived here.
        try:
            from . import preach
            so = preach.sermon_outlines(ref, limit=6) or {}
        except Exception:                                # noqa: BLE001
            so = {}
        for it in (so.get("items") or []):
            pts = [p for p in (it.get("points") or []) if p]
            if pts:
                add(it.get("module_id", ""), it.get("module", ""),
                    it.get("title", ""), "outline points", "SermonOutline",
                    "\n".join(pts))

        if (theme or "").strip():
            # The theme search runs over the library only.  Sermon research is
            # a contract about *published* sources the preacher can check, and
            # the reader's own notes are not that: quoting a preacher's
            # private note back to them as an outline point would be a strange
            # thing to do.  The reader's own material belongs to the chat,
            # where "what did I write about this" is a question that gets
            # asked out loud.
            for s in build_context(theme, max(2, max_sources // 2),
                                   use_mine=False):
                add(s["module_id"], s["module_name"], s["label"], s["title"],
                    s["type"], s["text"])

    if len(out) > max_sources:
        out = out[:max_sources]
        for i, s in enumerate(out):
            s["n"] = i + 1
    return out


def run_sermon(kind: str, ref: str, theme: str = "",
               provider_id: str | None = None, model: str | None = None,
               use_library: bool | None = None,
               max_sources: int | None = None) -> dict:
    """Full (non-streaming) sermon research.  Used by tests, and by callers that
    want the whole note at once; the UI streams the same request."""
    provider, model = resolve(provider_id, model)
    s = get_settings()
    if use_library is None:
        use_library = s.get("use_library", True)
    cap = max_sources or s.get("max_sources", 8)
    sources = sermon_sources(ref, theme, bool(use_library), max(cap, 10))
    msgs = sermon_messages(kind, ref, theme, sources)
    parts: list[str] = []
    stats: dict = {}
    for delta in stream(msgs, provider, model, stats=stats):
        parts.append(delta)
    record_usage(provider.id, model, f"sermon:{kind}", stats)
    return {
        "ok": True, "answer": "".join(parts), "action": kind, "sermon": kind,
        "ref": ref, "theme": theme, "provider": provider.id, "model": model,
        "citations": sources, "used_library": bool(use_library),
    }


# ==========================================================================
# Topic guide: the assistant answers from the guide's own installed material
# ==========================================================================
# A topic guide is a *place*, and the assistant's job there is to speak about
# the material the reader already has in front of them -- not to go and search
# the library again for passages about the word.  The reader has already
# decided what "grace" means to them by deciding what is installed; the model
# reasons over that, not over its own memory of the subject.
#
# So the corpus is the guide itself: the topical article, the verses it names,
# and the glosses.  A lookup-shaped section -- a concordance, an atlas caption,
# a Strong's number -- is left out for the same reason it is left out of chat
# grounding: it is not prose *about* the subject.
#
# The rule from everywhere else applies here hardest.  The answer cites the
# guide's own sources, and where the guide is silent the model says so rather
# than filling the gap from what it knows.

_TOPIC_SYSTEM = (
    "You answer questions about a topic using the reader's own installed "
    "library. The numbered sources below are that topic guide: the articles, "
    "glosses and verses they have on this subject. Work only from them and "
    "cite them by number. If they do not cover the question, say so plainly "
    "rather than drawing on general knowledge. Where two sources disagree, say "
    "that they disagree rather than choosing one."
)

#: How much of each kind of section the corpus may hold.  The topical article
#: comes first because it is what the reader came for; the verses come next
#: because they are what the topic is about in Scripture; the glosses come
#: last, because they are concise but shallow.  The three are balanced so that
#: none of them is squeezed out by the cap: a corpus of articles alone would
#: tell the model what the subject *is* and nothing about what the Bible says
#: about it.
_TOPIC_LIMITS = {"topic": 4, "verses": 5, "dictionary": 3}


def topic_sources(topic: str, guide: dict | None = None,
                   max_sources: int = 12) -> list[dict]:
    """The grounding for a topic guide: the guide's own installed material.

    The guide is gathered here rather than handed in by the browser, because
    what the model reads has to be what the *server* holds -- not what the
    client says it holds.
    """
    topic = (topic or "").strip()
    if not topic:
        raise AiError("No topic given.", hint="Open a topic guide first.")
    if guide is None:
        try:
            from . import study
            guide = study.topic_guide(topic) or {}
        except Exception as e:                            # noqa: BLE001
            raise AiError(f"Could not gather the guide for {topic!r}.",
                          hint=str(e) or "Try another topic.") from e
    if not guide.get("ok"):
        raise AiError(guide.get("error") or f"Cannot read {topic!r} as a topic.",
                      hint="Try another topic.")
    sections = guide.get("sections") or []
    if not sections:
        raise AiError(f"Nothing installed covers {topic}.",
                      hint="Install a topic or fact book, or try another topic.")

    out: list[dict] = []

    def add(module_id: str, module_name: str, label: str, title: str,
            mtype: str, text: str, key: str = "") -> bool:
        text = (text or "").strip()
        if not text or len(out) >= max_sources:
            return False
        if len(text) > 1200:
            text = text[:1200].rsplit(" ", 1)[0] + " …"
        out.append({"n": len(out) + 1, "module_id": module_id,
                    "module_name": module_name, "label": label,
                    "title": title, "type": mtype, "text": text, "key": key})
        return True

    for sec in sections:
        kind = sec.get("kind", "")
        if kind not in _TOPIC_LIMITS:
            continue
        left = _TOPIC_LIMITS[kind]
        for it in sec.get("items") or []:
            if left <= 0 or len(out) >= max_sources:
                break
            if kind == "verses":
                ok = add(it.get("module_id", ""), it.get("module", ""),
                         it.get("label", ""), it.get("title", ""), "Bible",
                         it.get("text", ""), it.get("key", ""))
            else:
                ok = add(it.get("module_id", ""), it.get("module", ""),
                         it.get("title", "") or it.get("key", ""),
                         it.get("title", ""),
                         "FactBook" if kind == "topic" else "Dictionary",
                         it.get("text", ""), it.get("key", ""))
            if ok:
                left -= 1
    if not out:
        raise AiError(
            f"Nothing installed covers {topic} in a form the assistant can read.",
            hint="Install a topic or fact book, or try another topic.")
    return out


def topic_messages(topic: str, question: str, sources: list[dict],
                   history: list[dict] | None = None) -> list[dict]:
    """The messages for one question about a topic.

    The shape is the same as every other call -- a system rule, the numbered
    sources, then the question -- so the citation list the reader clicks and
    the sources the model read are built from one list and cannot drift apart.
    """
    topic = (topic or "").strip()
    if not topic:
        raise AiError("No topic given.", hint="Open a topic guide first.")
    msgs: list[dict] = [{"role": "system", "content": _TOPIC_SYSTEM}]
    if sources:
        block = ["Numbered sources:", ""]
        for s in sources:
            title = s["label"] or s["title"] or s["module_name"]
            block.append(f"[{s['n']}] {s['module_name']} — {title}")
            block.append(s["text"])
            block.append("")
        block.append("Work from these. Cite them by number.")
        msgs.append({"role": "system", "content": "\n".join(block)})
    # A follow-up question is a follow-up: "what about the second one?" means
    # nothing without the answer it follows.  So the exchange so far is kept --
    # this topic's exchange only, never the reader's unrelated chat history.
    for h in (history or [])[-6:]:
        role = h.get("role")
        content = (h.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            msgs.append({"role": role, "content": content})
    q = (question or "").strip()
    if not q:
        raise AiError("Ask a question about the topic.",
                      hint="Type what you want to know.")
    msgs.append({"role": "user", "content": f"Topic: {topic}\n\n{q}"})
    return msgs


def run_topic(topic: str, question: str,
              provider_id: str | None = None, model: str | None = None,
              use_library: bool | None = None,
              max_sources: int | None = None) -> dict:
    """Full (non-streaming) topic answer.  Used by tests, and by callers that
    want the whole text at once; the UI streams the same request."""
    provider, model = resolve(provider_id, model)
    sources = topic_sources(topic, max_sources=max_sources or 12)
    msgs = topic_messages(topic, question, sources)
    parts: list[str] = []
    stats: dict = {}
    for delta in stream(msgs, provider, model, stats=stats):
        parts.append(delta)
    record_usage(provider.id, model, "topic:ask", stats)
    return {
        "ok": True, "answer": "".join(parts), "action": "topic",
        "topic": topic, "provider": provider.id, "model": model,
        "citations": sources,
    }


# ==========================================================================
# The questions a topic guide offers
# ==========================================================================
# The topic guide offers "Questions to Ask": a handful of questions that spark
# exploration, each of which opens an answer with citations, and each of which
# can be carried into the conversation.  The questions are what make the
# section worth opening -- a topic guide that only
# lists what is in it is a list.
#
# The questions here are written by the model, from the guide's own material,
# because the guide is assembled from what the reader happens to have
# installed: a question written for one reader's library is often about
# something another reader's library does not contain.  The model sees the
# same sources the answers are grounded in, so a question it writes can
# actually be answered from them.
#
# It is a separate call from the answer, and it is a small one: the questions
# are four short lines, and a reader should not wait for an overview to
# finish before they can see what they might ask about.

_QUESTIONS_SYSTEM = (
    "You write the questions a reader would want to ask about a topic. You "
    "are given the material on that topic. Write four questions the reader "
    "could ask about it, each of them answerable from the material you are "
    "given. Follow these rules:\n"
    "1. Ask about what is actually here -- a claim the sources make, a term "
    "they use, a tension between them, a passage they lean on -- and not "
    "about the subject in general.\n"
    "2. Do not ask what the sources say about the topic. That is too broad to "
    "answer. Ask something narrower, that a reader could get a real answer "
    "to.\n"
    "3. Ask about the sources, not about the reader. No question about what "
    "the reader should believe or do.\n"
    "4. Reply with the four questions only, one per line, numbered 1 to 4, "
    "and nothing else. No preamble, no explanation, no code fence."
)


def topic_fallback_questions(topic: str) -> list[dict]:
    """The questions a topic guide offers when the model cannot be reached.

    An empty set of suggested questions is worse than a generic one, and the
    model is the thing most likely to be unavailable -- so the guide keeps a
    set that always works.

    The shape is the same as the model's own questions -- a question and a
    one-line answer -- so the interface renders them one way whether they came
    from the model or from here.
    """
    t = (topic or "").strip()
    return [{"question": q, "answer": ""} for q in [
        (f"What does the Bible say about {t}?" if t
         else "What does the Bible say about this topic?"),
        "What are the key terms?",
        "Where do the sources disagree?",
        "What do the glosses add?",
    ]]


def _parse_questions(raw: str, limit: int = 5) -> list[str]:
    """The questions out of a model's reply.

    Models wrap a list in whatever they please -- a code fence, a "Here are
    the questions:" line, quotes, bold around the number -- so the line is
    taken apart rather than the whole reply trusted.  A line that is not a
    question is dropped: a model that answered the question it was asked, in
    statements, has not written the questions, and the fallback ones are
    better than that.
    """
    out: list[str] = []
    for line in (raw or "").splitlines():
        s = line.strip()
        if not s or s.startswith("```"):
            continue
        s = s.strip("\"'“”‘’ ")
        # The number, the bullet and the markdown around them are decoration:
        # "1.", "1)", "- ", "**1.**" and "### 1." all mean the same thing.
        s = re.sub(r"^[*_#\s>-]+", "", s)
        s = re.sub(r"^\d+\s*[.)]\s*", "", s)
        s = re.sub(r"^[*_`\s]+", "", s)
        s = s.strip("\"'“”‘’ ")
        if not s.endswith("?") or len(s) > 200:
            continue
        if s not in out:
            out.append(s)
        if len(out) >= limit:
            break
    return out


def topic_questions(topic: str, provider_id: str | None = None,
                    model: str | None = None,
                    max_sources: int | None = None) -> dict:
    """The questions a topic guide should offer, written from its own material.

    Never raises: a model that cannot be reached costs the reader their
    suggested questions and nothing else, and the guide has a set that always
    works.
    """
    topic = (topic or "").strip()
    fallback = topic_fallback_questions(topic)
    if not topic:
        return {"ok": True, "questions": fallback, "provider": "", "model": ""}
    try:
        provider, model = resolve(provider_id, model)
        sources = topic_sources(topic, max_sources=max_sources or 12)
    except Exception:                                    # noqa: BLE001
        return {"ok": True, "questions": fallback, "provider": "",
                "model": "", "fallback": True}
    if not sources:
        return {"ok": True, "questions": fallback, "provider": provider.id,
                "model": model, "fallback": True}
    block = ["Material on this topic:", ""]
    for s in sources:
        title = s["label"] or s["title"] or s["module_name"]
        block.append(f"[{s['n']}] {s['module_name']} — {title}")
        block.append(s["text"])
        block.append("")
    msgs = [
        {"role": "system", "content": _QUESTIONS_SYSTEM},
        {"role": "system", "content": "\n".join(block)},
        {"role": "user", "content": f"Topic: {topic}\n\n"
                                    "Write the four questions."},
    ]
    parts: list[str] = []
    stats: dict = {}
    try:
        for delta in stream(msgs, provider, model, stats=stats):
            parts.append(delta)
    except Exception:                                    # noqa: BLE001
        return {"ok": True, "questions": fallback, "provider": provider.id,
                "model": model, "fallback": True}
    record_usage(provider.id, model, "topic:questions", stats)
    questions = [{"question": q, "answer": ""}
                 for q in _parse_questions("".join(parts))]
    if not questions:
        return {"ok": True, "questions": fallback, "provider": provider.id,
                "model": model, "fallback": True}
    return {"ok": True, "questions": questions, "provider": provider.id,
            "model": model}


# ==========================================================================
# Transport: one call per adapter, streamed
# ==========================================================================

class AiError(Exception):
    """A refused or failed provider call, with a hint for the reader.

    `status` is the HTTP code when the provider answered at all, so a caller can
    tell "this server does not understand the request" (400) from "the network is
    down" without re-reading the message text.
    """

    def __init__(self, message: str, hint: str = "", status: int = 0):
        super().__init__(message)
        self.hint = hint
        self.status = status


def _detail(raw: bytes) -> str:
    """The provider's own explanation of a failure, if it gave one."""
    try:
        d = json.loads(raw.decode("utf-8", "replace"))
    except Exception:                                    # noqa: BLE001
        return ""
    if isinstance(d, dict):
        for k in ("error", "message", "detail"):
            v = d.get(k)
            if isinstance(v, dict) and isinstance(v.get("message"), str):
                return v["message"][:300]
            if isinstance(v, str) and v.strip():
                return v.strip()[:300]
    return ""


def _request(provider: Provider, path: str, payload: dict,
             headers: dict, timeout: int) -> urllib.request.Request:
    url = provider.base_url + path
    body = json.dumps(payload).encode("utf-8")
    hdrs = {
        "User-Agent": _USER_AGENT,
        "Content-Type": "application/json",
        "Accept": "text/event-stream, application/json",
        **headers,
    }
    return urllib.request.Request(url, data=body, headers=hdrs, method="POST")


def _auth_headers(provider: Provider, optional: bool = False) -> dict:
    if not provider.key_required:
        return {}
    key = key_for(provider.id).strip()
    if not key:
        # A provider that publishes its model list without a key can still be
        # listed: the reader sees what is on offer before deciding to sign up.
        # Anything else is a request that cannot succeed, and says so.
        if optional and provider.list_without_key:
            return {}
        raise AiError(
            f"No API key set for {provider.name}.",
            hint="Add it in Settings → AI, then try again.")
    if provider.adapter == "anthropic":
        return {"x-api-key": key, "anthropic-version": "2023-06-01"}
    return {"Authorization": f"Bearer {key}"}


def _openai_payload(messages: list[dict], model: str,
                    usage: bool = True) -> dict:
    p = {"model": model, "messages": messages, "stream": True,
         "temperature": 0.2, "max_tokens": 1024}
    # `include_usage` is an OpenAI extension that appends one final chunk with
    # the token counts -- the only way to meter a *streamed* call, since the
    # normal usage field rides on a non-streaming reply.  Servers that implement
    # the OpenAI shape but not this option reject the whole request with a 400,
    # so `stream()` drops it and retries once (see `_NO_USAGE`).
    if usage:
        p["stream_options"] = {"include_usage": True}
    return p


def _anthropic_payload(messages: list[dict], model: str) -> dict:
    # Anthropic wants the system prompt separate and has no "system" role in the
    # messages list, so it is split out rather than passed through.
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    chat = [{"role": m["role"], "content": m["content"]}
            for m in messages if m["role"] in ("user", "assistant")]
    return {"model": model, "system": system, "messages": chat,
            "stream": True, "temperature": 0.2, "max_tokens": 1024}


def _ollama_payload(messages: list[dict], model: str) -> dict:
    return {"model": model, "messages": messages, "stream": True,
            "options": {"temperature": 0.2}}


def _payload_for(provider: Provider, messages: list[dict], model: str,
                 usage: bool = False) -> dict:
    if provider.adapter == "openai":
        return _openai_payload(messages, model, usage)
    if provider.adapter == "anthropic":
        return _anthropic_payload(messages, model)
    if provider.adapter == "ollama":
        return _ollama_payload(messages, model)
    raise AiError(f"Unknown adapter: {provider.adapter}")


def _iter_sse_lines(resp) -> Iterator[str]:
    """Yield the `data:` payload of each server-sent-event line."""
    for raw in resp:
        line = raw.decode("utf-8", "replace").strip()
        if not line or not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            return
        yield data


#: Providers seen to reject `stream_options`.  Learned once, at the cost of one
#: rejected request, and then never asked of that provider again -- the flag is
#: an OpenAI extension and the servers that speak the shape without implementing
#: it are exactly the local ones, where a needless round trip is most noticeable.
_NO_USAGE: set[str] = set()


def _open_stream(provider: Provider, payload: dict, headers: dict,
                 timeout: int):
    """POST a streaming payload and hand back the live response."""
    req = _request(provider, _PATH[provider.adapter], payload, headers, timeout)
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        body = b""
        try:
            body = e.read(_MAX_BYTES)
        except Exception:                                # noqa: BLE001
            pass
        msg = _detail(body) or f"HTTP {e.code}: {e.reason}"
        raise AiError(f"{provider.name}: {msg}", status=e.code) from e
    except urllib.error.URLError as e:
        raise AiError(
            f"Could not reach {provider.name}: {e.reason}",
            hint=(provider.start_hint
                  or ("Is the local server running?" if provider.local
                      else "Check your network connection."))) from e


def stream(messages: list[dict], provider: Provider, model: str,
           timeout: int = 120, stats: dict | None = None) -> Iterator[str]:
    """Yield answer text deltas from `provider`.

    One generator for all three adapters: the differences between the wire
    formats are confined to the payload builder and the extractors below, so the
    caller never branches on vendor.

    `stats`, if given, is filled in with whatever token counts the provider
    reports -- the extractors write into it as they parse.  It is best effort by
    design: a provider that reports nothing leaves it empty and the call is
    still metered, as a call, because "three calls, tokens unknown" is truer
    than no record at all.
    """
    st = stats if stats is not None else {}
    headers = _auth_headers(provider)
    usage = provider.adapter == "openai" and provider.id not in _NO_USAGE
    payload = _payload_for(provider, messages, model, usage)
    try:
        resp = _open_stream(provider, payload, headers, timeout)
    except AiError as e:
        # A 400 on the first OpenAI-shaped call usually means the server has no
        # `stream_options`.  Metering is worth one retry, not a broken feature:
        # drop the option, remember, and send again.
        if usage and e.status == 400:
            _NO_USAGE.add(provider.id)
            payload = _payload_for(provider, messages, model, False)
            resp = _open_stream(provider, payload, headers, timeout)
        else:
            raise

    with resp:
        yield from _extract[provider.adapter](resp, st)


_PATH = {"openai": "/chat/completions", "anthropic": "/messages",
         "ollama": "/api/chat"}


def _x_openai(resp, st: dict) -> Iterator[str]:
    for data in _iter_sse_lines(resp):
        try:
            d = json.loads(data)
        except json.JSONDecodeError:
            continue
        # With `stream_options.include_usage` the counts arrive on a final chunk
        # that has no choices at all, so this must be read before the loop below
        # and must not depend on one.
        _take_usage(st, d.get("usage"), "prompt_tokens", "completion_tokens")
        for ch in d.get("choices") or []:
            delta = ch.get("delta") or {}
            if delta.get("content"):
                yield delta["content"]


def _x_anthropic(resp, st: dict) -> Iterator[str]:
    for data in _iter_sse_lines(resp):
        try:
            d = json.loads(data)
        except json.JSONDecodeError:
            continue
        # Anthropic splits usage across the stream: input tokens arrive with
        # `message_start`, output tokens with the `message_delta` at the end.
        kind = d.get("type")
        if kind == "message_start":
            u = (d.get("message") or {}).get("usage") or {}
            if u.get("input_tokens") is not None:
                st["prompt_tokens"] = int(u["input_tokens"] or 0)
        elif kind == "message_delta":
            u = d.get("usage") or {}
            if u.get("output_tokens") is not None:
                st["completion_tokens"] = int(u["output_tokens"] or 0)
        elif kind == "content_block_delta":
            delta = d.get("delta") or {}
            if delta.get("type") == "text_delta" and delta.get("text"):
                yield delta["text"]


def _x_ollama(resp, st: dict) -> Iterator[str]:
    for raw in resp:
        line = raw.decode("utf-8", "replace").strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        # Ollama's final line, `done: true`, carries the counts under its own
        # names rather than a `usage` object.
        if d.get("done"):
            if d.get("prompt_eval_count") is not None:
                st["prompt_tokens"] = int(d["prompt_eval_count"] or 0)
            if d.get("eval_count") is not None:
                st["completion_tokens"] = int(d["eval_count"] or 0)
        msg = d.get("message") or {}
        if msg.get("content"):
            yield msg["content"]


def _take_usage(st: dict, usage, in_key: str, out_key: str) -> None:
    """Copy a `{input, output}` usage object into `st` under our own names."""
    if not isinstance(usage, dict):
        return
    if usage.get(in_key) is not None:
        st["prompt_tokens"] = int(usage[in_key] or 0)
    if usage.get(out_key) is not None:
        st["completion_tokens"] = int(usage[out_key] or 0)
    if usage.get("total_tokens") is not None:
        st["total_tokens"] = int(usage["total_tokens"] or 0)


_extract = {"openai": _x_openai, "anthropic": _x_anthropic,
            "ollama": _x_ollama}


# ==========================================================================
# Usage: what the calls have been
# ==========================================================================
# A local model is free and stays free.  A cloud one is billed per token, and
# from inside a desktop app there is no way to see a month's use without going
# to the provider's website and working out which of the calls were yours.  So
# every call is written down as it happens: which provider, which model, what it
# was for, and the token counts the provider itself reported.  Nothing here is
# estimated -- a provider that reports no counts logs none rather than a
# plausible number, because a made-up figure is worse than a gap for somebody
# checking a bill.

#: Approximate list prices, US dollars per million tokens (input, output), for
#: the cloud models named in `PROVIDERS`.  Prices change, so these are labelled
#: approximate wherever they surface and an unknown model is shown with its
#: token count and no cost.  Longest prefix wins, so "gpt-4o-mini" is not
#: priced as "gpt-4o" -- the order of this dict is deliberately not load-bearing.
_PRICES: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
    "claude-3-5-haiku": (0.80, 4.00),
    "claude-3-5-sonnet": (3.00, 15.00),
    "claude-3-opus": (15.00, 75.00),
}


def price_for(model: str):
    """(input, output) USD per million tokens, or None when the model is unknown."""
    m = (model or "").lower()
    best: str = ""
    for prefix in _PRICES:
        if m.startswith(prefix) and len(prefix) > len(best):
            best = prefix
    return _PRICES[best] if best else None


def _is_free_model(provider_id: str, model: str) -> bool:
    """Is this model one that costs nothing to call?

    Two kinds of knowledge, and the difference between them matters:

    * A provider that *filters* its listing to the free models (OpenRouter)
      names them with a `:free` suffix.  That suffix is the provider's own
      promise rather than our inference, so it is trusted.
    * A free-*tier* provider (Groq, Google) serves the very same model id on a
      paid account, for money.  The app cannot see which account the reader
      has, so the provider's free-tier list is the best answer available — and
      the usage card says plainly that it is an assumption, rather than
      pretending to know.
    """
    mid = (model or "").strip().lower()
    if mid.endswith(":free") or mid == "openrouter/free":
        return True
    p = BY_ID.get(provider_id or "")
    if p is not None and p.free and model in p.models:
        return True
    return False


def cost_of(provider_id: str, model: str, prompt_tokens: int,
            completion_tokens: int):
    """Estimated USD for one call, or None when the model cannot be priced.

    A free model is a *known* zero rather than an unknown: "this call cost
    nothing" and "this call's cost is not known" are different statements, and
    only the second one is a gap.
    """
    if _is_free_model(provider_id, model):
        return 0.0
    p = price_for(model)
    if not p:
        return None
    return ((prompt_tokens or 0) / 1_000_000 * p[0]
            + (completion_tokens or 0) / 1_000_000 * p[1])


def record_usage(provider_id: str, model: str, kind: str,
                 stats: dict | None = None, ok: bool = True) -> None:
    """Write one call down.  Never raises.

    Metering sits on the path of the thing it measures, so a failure to write it
    must not become a failure to answer.  A call that errored *after* being sent
    is still recorded, with `ok = 0`: that is exactly the row a reader wants when
    a bill does not match their impression of what they used.
    """
    try:
        st = stats or {}
        pt = int(st.get("prompt_tokens") or 0)
        ct = int(st.get("completion_tokens") or 0)
        tt = int(st.get("total_tokens") or (pt + ct))
        conn = db.connect()
        conn.execute(
            "INSERT INTO ai_usage(at,provider,model,kind,prompt_tokens,"
            "completion_tokens,total_tokens,ok) VALUES(?,?,?,?,?,?,?,?)",
            (time.time(), provider_id or "", model or "", kind or "chat",
             pt, ct, tt, 1 if ok else 0))
        conn.commit()
    except Exception:                                    # noqa: BLE001
        pass


def _usage_bucket() -> dict:
    return {"calls": 0, "failed": 0, "prompt_tokens": 0, "completion_tokens": 0,
            "total_tokens": 0, "cost": 0.0, "priced": 0, "cost_known": True}


def _fold(bucket: dict, row) -> None:
    bucket["calls"] += 1
    if not row["ok"]:
        bucket["failed"] += 1
    pt = int(row["prompt_tokens"] or 0)
    ct = int(row["completion_tokens"] or 0)
    bucket["prompt_tokens"] += pt
    bucket["completion_tokens"] += ct
    bucket["total_tokens"] += int(row["total_tokens"] or 0) or (pt + ct)
    c = cost_of(row["provider"], row["model"], pt, ct)
    if c is None:
        # A local model with no price on file is not a gap in the figures, it is
        # a free call: only an unpriced *cloud* model makes the cost a floor
        # rather than a total.  A provider we do not recognise is treated as
        # cloud, because guessing that something unknown is free is the error
        # that costs money.
        p = BY_ID.get(row["provider"] or "")
        cloud = p is None or not p.local
        if cloud and (pt or ct):
            bucket["cost_known"] = False
    else:
        bucket["cost"] += c
        bucket["priced"] += 1


def usage_summary(days: int = 30) -> dict:
    """Totals for the last `days` days, overall, by provider and by model."""
    try:
        days = max(1, min(3650, int(days or 30)))
    except (TypeError, ValueError):
        days = 30
    since = time.time() - days * 86400
    conn = db.connect()
    rows = conn.execute(
        "SELECT at,provider,model,kind,ok,prompt_tokens,completion_tokens,"
        "total_tokens FROM ai_usage WHERE at >= ? ORDER BY at DESC",
        (since,)).fetchall()

    total = _usage_bucket()
    by_provider: dict[str, dict] = {}
    by_model: dict[str, dict] = {}
    for r in rows:
        _fold(total, r)
        pid = r["provider"] or ""
        _fold(by_provider.setdefault(pid, _usage_bucket()), r)
        mk = f"{pid}\u0000{r['model'] or ''}"
        _fold(by_model.setdefault(mk, _usage_bucket()), r)

    def named(b: dict, pid: str) -> dict:
        p = BY_ID.get(pid)
        return {**{k: v for k, v in b.items()},
                "provider": pid,
                "name": (p.name if p else (pid or "unknown")),
                "local": bool(p.local) if p else False,
                "cost": round(b["cost"], 4)}

    providers = sorted(
        (named(b, pid) for pid, b in by_provider.items()),
        key=lambda x: (-x["total_tokens"], -x["calls"]))
    models = []
    for mk, b in by_model.items():
        pid, _, model = mk.partition("\u0000")
        m = named(b, pid)
        m["model"] = model
        m["cost"] = round(b["cost"], 4)
        models.append(m)
    models.sort(key=lambda x: (-x["total_tokens"], -x["calls"]))
    total["cost"] = round(total["cost"], 4)

    note = ""
    cloud = [p for p in providers if not p["local"]]
    if cloud and not total["cost_known"]:
        note = ("Some models have no price on file, so the cost is a floor. "
                "Token counts are exact.")
    elif cloud and total["calls"] and not total["priced"]:
        note = ("No price on file for the models used, so only the token counts "
                "are shown.")
    # A free tier is an assumption, not a fact the app can check: the same
    # model id is charged for on a billed account.  Saying so here is the
    # difference between a zero and a zero the reader trusts.
    assumed_free = sorted({p["provider"] for p in cloud
                            if BY_ID.get(p["provider"]) and BY_ID[p["provider"]].free})
    if assumed_free:
        names = ", ".join(BY_ID[pid].name for pid in assumed_free
                          if BY_ID.get(pid))
        tail = ("Free tier assumed for " + names + ": a free-tier provider "
                "charges for the same model on a paid account, so check the "
                "bill if you have enabled one.")
        note = (note + " " + tail).strip() if note else tail
    return {"ok": True, "days": days, "since": since,
            "calls": total["calls"], "failed": total["failed"],
            "prompt_tokens": total["prompt_tokens"],
            "completion_tokens": total["completion_tokens"],
            "total_tokens": total["total_tokens"],
            "cost": total["cost"], "cost_known": total["cost_known"],
            "providers": providers, "models": models, "note": note,
            "prices": "approximate, list price at the time of writing"}


def reset_usage() -> dict:
    """Forget every recorded call.  A reader's own numbers are theirs to clear."""
    conn = db.connect()
    n = conn.execute("SELECT count(*) FROM ai_usage").fetchone()[0]
    conn.execute("DELETE FROM ai_usage")
    conn.commit()
    return {"ok": True, "cleared": int(n)}


# ==========================================================================
# Reaching a provider: list its models, which is also the liveness test
# ==========================================================================

def _get_json(provider: Provider, path: str, timeout: int) -> dict:
    """GET `path` from a provider and decode the JSON reply."""
    hdrs = {
        "User-Agent": _USER_AGENT,
        "Accept": "application/json",
        **_auth_headers(provider, optional=True),
    }
    req = urllib.request.Request(provider.base_url + path, headers=hdrs,
                                 method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read(_MAX_BYTES)
    return json.loads(raw.decode("utf-8", "replace"))


#: Where each adapter lists the models it has.  Ollama answers `/api/tags`;
#: everything else that can be listed speaks the OpenAI/Anthropic `/models`
#: shape (llama.cpp and LM Studio include).
_MODELS_PATH = {"ollama": "/api/tags", "anthropic": "/models?limit=100",
                "openai": "/models"}


def _model_items(adapter: str, d: dict) -> list[dict]:
    """The raw model objects a provider listed, in its own shape.

    The OpenAI shape is `{"data": [{"id": ...}]}`.  Some providers answer with
    `{"models": [...]}` instead -- Google does on its native endpoint -- and the
    reader should get a model list either way, so both shapes are read.
    """
    if adapter == "ollama":
        items = d.get("models") or []
    else:
        items = d.get("data") or d.get("models") or []
    return [m for m in items if isinstance(m, dict)]


def _model_name(adapter: str, m: dict) -> str:
    if adapter == "ollama":
        return m.get("name") or m.get("model") or ""
    name = m.get("id") or m.get("name") or ""
    # Google's native listing prefixes every name with the resource type.
    return str(name)[7:] if str(name).startswith("models/") else str(name)


def _model_names(adapter: str, d: dict) -> list[str]:
    return [n for n in (_model_name(adapter, m)
                        for m in _model_items(adapter, d)) if n]


def probe(provider_id: str | None = None, timeout: int = 8) -> dict:
    """Ask a provider which models it has, which doubles as a liveness test.

    A successful listing is the cheapest honest answer to "can I reach it, and
    am I allowed in" there is: it needs no prompt, spends no tokens, and returns
    the *real* model names rather than the ones guessed at in `PROVIDERS`.  That
    is what makes it the right thing for the Test button -- a preset list is a
    promise the software cannot keep, and the reader finds out it was wrong only
    when a question fails.

    Never raises: a failure is part of the answer, because the reader asked "is
    it reachable" and "no" is a valid reply.
    """
    provider = get_provider(provider_id or get_settings()["provider"])
    out: dict = {"ok": False, "provider": provider.id, "name": provider.name,
                 "local": provider.local, "reachable": False, "models": [],
                 "error": "", "hint": ""}
    try:
        d = _get_json(provider, _MODELS_PATH[provider.adapter], timeout)
    except AiError as e:
        # A credential problem is settled locally, before any request goes out.
        out["error"] = str(e)
        out["hint"] = e.hint
        return out
    except urllib.error.HTTPError as e:
        body = b""
        try:
            body = e.read(_MAX_BYTES)
        except Exception:                                # noqa: BLE001
            pass
        # An HTTP error means the server answered -- it is reachable, it just
        # refused.  The difference matters: "wrong key" and "not running" send
        # the reader to two different places.
        out["reachable"] = True
        out["error"] = _detail(body) or f"HTTP {e.code}: {e.reason}"
        if e.code in (401, 403):
            out["hint"] = (f"The key for {provider.name} was refused. "
                           "Check it in Settings → AI.")
        return out
    except urllib.error.URLError as e:
        out["error"] = f"Could not reach {provider.name} ({provider.base_url})."
        out["hint"] = (provider.start_hint
                       or ("Is the local server running?" if provider.local
                           else "Check your network connection."))
        out["detail"] = str(e.reason)
        return out
    except Exception as e:                               # noqa: BLE001
        out["error"] = f"{type(e).__name__}: {e}"
        return out
    out["ok"] = True
    out["reachable"] = True
    items = _model_items(provider.adapter, d)
    if provider.free_filter:
        # A provider that aggregates other people's models lists all of them,
        # of every price.  The filter narrows the list to the ones the reader
        # came for, and the number hidden is reported rather than dropped
        # silently -- a list that quietly lost 300 entries would look like the
        # provider only has six models.
        kept = [m for m in items if provider.free_filter(m)]
        out["models"] = sorted({n for n in (_model_name(provider.adapter, m)
                                            for m in kept) if n})
        out["hidden"] = len(items) - len(kept)
    else:
        out["models"] = sorted({n for n in _model_names(provider.adapter, d)})
    return out


# ==========================================================================
# The one call the endpoints make
# ==========================================================================

def resolve(provider_id: str | None = None, model: str | None = None
            ) -> tuple[Provider, str]:
    """Pick the provider/model, falling back to the saved settings."""
    s = get_settings()
    provider = get_provider(provider_id or s["provider"])
    explicit = (model or "").strip()
    model = explicit or (s.get("model") or "").strip()
    # A model name belongs to the provider it came from.  Sending "llama3.1" to
    # Groq is a 404 the reader cannot explain, so when the provider named here
    # is not the one the *saved* model belongs to, the saved model is dropped in
    # favour of one of this provider's own.  A model the caller asked for by
    # name is never second-guessed -- that is the caller's business, and the
    # provider will say so plainly if it does not exist.
    if (not explicit and provider.id != s.get("provider")
            and (not provider.models or model not in provider.models)):
        model = ""
    if not model and provider.models:
        model = provider.models[0]
    if not model:
        # A provider with no preset list has to be asked what it has: a local
        # OpenAI-compatible server serves whatever model is loaded, and
        # OpenRouter's free roster rotates.  The reader cannot pick from a list
        # that has not been fetched yet, so the hint says to fetch it rather
        # than to "pick a model" from an empty dropdown.
        raise AiError(
            f"No model chosen for {provider.name}.",
            hint=("Press Test in Settings → AI to list the models it has."
                  if not provider.models
                  else "Pick a model in Settings → AI."))
    return provider, model


def chat(question: str, history: list[dict] | None = None,
         provider_id: str | None = None, model: str | None = None,
         use_library: bool | None = None, use_mine: bool | None = None,
         scope: str | None = None, context: dict | None = None,
         max_sources: int | None = None, semantic: bool | None = None,
         smart_query: bool | None = None) -> dict:
    """Full (non-streaming) answer.  Used by tests and by callers that want the
    whole text at once; the UI prefers the streaming path."""
    provider, model = resolve(provider_id, model)
    s = get_settings()
    if use_library is None:
        use_library = s.get("use_library", True)
    if use_mine is None:
        use_mine = s.get("use_mine", True)
    if scope is None:
        scope = s.get("scope", "")
    if semantic is None:
        semantic = s.get("semantic", True)
    if smart_query is None:
        smart_query = s.get("smart_query", True)
    sources = build_context(question, max_sources or s.get("max_sources", 8),
                            use_library=bool(use_library),
                            use_mine=bool(use_mine), scope=scope or "",
                            context=context, provider=provider,
                            semantic=bool(semantic),
                            smart_query=bool(smart_query), model=model)
    msgs = build_messages(question, history, sources, context)
    parts: list[str] = []
    stats: dict = {}
    for delta in stream(msgs, provider, model, stats=stats):
        parts.append(delta)
    record_usage(provider.id, model, "chat", stats)
    return {
        "ok": True, "answer": "".join(parts), "provider": provider.id,
        "model": model, "citations": sources, "used_library": bool(use_library),
        "used_mine": bool(use_mine), "scope": scope or "",
    }


def run_action(kind: str, text: str, label: str = "", target: str = "",
               provider_id: str | None = None, model: str | None = None,
               use_library: bool | None = None, use_mine: bool | None = None,
               scope: str | None = None, max_sources: int | None = None,
               semantic: bool | None = None,
               smart_query: bool | None = None) -> dict:
    """Full (non-streaming) result for explain / summarize / translate.

    The same builder the streaming path uses, so the two can never disagree about
    what the model was told -- the only difference between them is whether the
    reader watches the tokens arrive.
    """
    provider, model = resolve(provider_id, model)
    s = get_settings()
    if use_library is None:
        use_library = s.get("use_library", True)
    if use_mine is None:
        use_mine = s.get("use_mine", True)
    if scope is None:
        scope = s.get("scope", "")
    if semantic is None:
        semantic = s.get("semantic", True)
    if smart_query is None:
        smart_query = s.get("smart_query", True)
    sources = action_sources(kind, text, label, bool(use_library),
                             max_sources or s.get("max_sources", 8),
                             use_mine=bool(use_mine), scope=scope or "",
                             provider=provider, semantic=bool(semantic),
                             smart_query=bool(smart_query), model=model)
    msgs = action_messages(kind, text, label, target, sources)
    parts: list[str] = []
    stats: dict = {}
    for delta in stream(msgs, provider, model, stats=stats):
        parts.append(delta)
    record_usage(provider.id, model, f"action:{kind}", stats)
    return {
        "ok": True, "answer": "".join(parts), "action": kind,
        "provider": provider.id, "model": model, "citations": sources,
        "used_library": bool(use_library), "used_mine": bool(use_mine),
        "scope": scope or "",
    }
