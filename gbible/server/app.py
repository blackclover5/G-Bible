from __future__ import annotations

import json
import mimetypes
import os
import re
import secrets
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .. import ai, db, publish, sync, tts
from .routes import (
    CSRF_HEADER, CSRF_TOKEN, FILE_ROUTES, VERSION, _ai_context, route,
)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


class _ClientGone(Exception):
    """Raised when a streamed response's reader has hung up."""


# --------------------------------------------------------------------------
# HTTP plumbing
# --------------------------------------------------------------------------

#: Hosts this server answers to.  Binding to 127.0.0.1 is not on its own
#: protection, and the reason is DNS rebinding: a page on a domain the attacker
#: controls can resolve to 127.0.0.1, after which the browser considers it
#: *same-origin* with this app.  There is no CORS to defeat, because there is no
#: cross-origin request -- the request looks local.  Everything the API can do,
#: including indexing and installing a file chosen by the caller, becomes
#: available to a page the user merely visited.
#:
#: The browser sends the Host header the user actually typed, so refusing
#: anything but the loopback names closes it.  A rebinding attack cannot forge
#: Host: the browser sets it from the URL it resolved, and that URL is the
#: attacker's domain, not 127.0.0.1.
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1"}


def _confined(path: str) -> bool:
    """Is a file inside the user's home directory?

    Used for audio only.  Local *imports* are deliberately not confined: being
    able to install a module from a USB stick at /media or a network mount is
    the point of "install from this computer", and those paths are not under
    $HOME.  The Host/Origin checks and CSRF token protect that endpoint from
    requests initiated by other sites.
    """
    from pathlib import Path as _P
    try:
        real = _P(path).resolve()
        real.relative_to(_P.home().resolve())
    except (OSError, ValueError):
        return False
    return True


def _host_allowed(host: str) -> bool:
    """Is this Host header ours?  Compares the name, not the port."""
    name = (host or "").strip()
    if name.startswith("["):                       # [::1]:8777
        name = name.split("]", 1)[0] + "]"
    elif name.count(":") == 1:                     # 127.0.0.1:8777
        name = name.rsplit(":", 1)[0]
    return name.lower() in ALLOWED_HOSTS


class Handler(BaseHTTPRequestHandler):
    server_version = f"GBible/{VERSION}"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        if os.environ.get("GBIBLE_VERBOSE"):
            super().log_message(fmt, *args)

    def _guard(self) -> bool:
        """Refuse a request that did not come from the app's own page.

        The Host check stops DNS rebinding.  An Origin, when present, must
        match the exact local origin; stateful routes additionally require the
        per-process token checked by _csrf_guard().
        """
        host = self.headers.get("Host", "")
        if not _host_allowed(host):
            self._send(403, b"This server only answers to localhost.",
                       "text/plain; charset=utf-8")
            db.log_history("blocked-request", f"Host: {host!r}", {"host": host})
            return False
        origin = self.headers.get("Origin")
        if origin:
            o = urllib.parse.urlparse(origin)
            if (o.scheme != "http" or o.netloc.lower() != host.strip().lower()
                    or o.username or o.password or o.path not in ("", "/")
                    or o.query or o.fragment):
                self._send(403, b"Cross-origin requests are refused.",
                           "text/plain; charset=utf-8")
                db.log_history("blocked-request", f"Origin: {origin!r}",
                               {"origin": origin})
                return False
        return True

    def _csrf_guard(self) -> bool:
        """Require proof that a stateful request came from this app's page."""
        site = (self.headers.get("Sec-Fetch-Site") or "").lower()
        token = self.headers.get(CSRF_HEADER, "")
        if site == "cross-site" or not secrets.compare_digest(token, CSRF_TOKEN):
            self._send(403, b"Request verification failed.",
                       "text/plain; charset=utf-8")
            db.log_history("blocked-request", "CSRF validation failed",
                           {"fetch_site": site})
            return False
        return True

    def _send(self, code: int, body: bytes, ctype: str, *, cache: bool = False):
        # Compress text responses when the client accepts gzip.  The browser
        # does the decoding, and the saving on a 15k-line JS file is large.
        ae = (self.headers.get("Accept-Encoding") or "").lower()
        if "gzip" in ae and (ctype.startswith("text/") or ctype.startswith("application/json")
                             or ctype.startswith("application/javascript")):
            import gzip as _gzip
            gz = _gzip.compress(body, compresslevel=6)
            if len(gz) < len(body):
                body = gz
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Encoding", "gzip")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "max-age=300" if cache else "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass
                return
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "max-age=300" if cache else "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _serve_audio(self, params):
        """Stream one registered recording.

        The path comes from the stored unit, never from the request, so this
        cannot be used to read arbitrary files off the disk -- a caller can only
        reach what was registered against that module id.
        """
        import os as _os
        mid = params.get("id", "")
        key = params.get("key", "")
        row = db.connect().execute(
            "SELECT extra FROM unit WHERE module_id=? AND key=?",
            (mid, key)).fetchone()
        if row is None:
            return self._send(404, b"no such recording", "text/plain")
        try:
            ex = json.loads(row["extra"] or "{}")
        except (json.JSONDecodeError, TypeError):
            ex = {}
        path = ex.get("file", "")
        # Re-check the confinement at serve time, not only at register time.
        # The stored path is trustworthy because we wrote it, but a database
        # restored from a backup, or one written before the confinement existed,
        # would otherwise stream whatever it names.
        if not path or not _confined(path):
            return self._send(404, b"the file is not where it was registered",
                              "text/plain")
        if not _os.path.isfile(path):
            return self._send(404, b"the file is not there any more",
                              "text/plain")
        try:
            data = _os.path.getsize(path)
            with open(path, "rb") as fh:
                body = fh.read()
        except OSError:
            return self._send(500, b"could not read the file", "text/plain")
        ctype = mimetypes.guess_type(path)[0] or "audio/mpeg"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(data))
        self.send_header("Cache-Control", "max-age=300")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Accept-Ranges", "none")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _serve_tts(self, raw: bytes):
        """Speak one passage and hand back the WAV.

        A POST, not a GET, and deliberately off the /api/ dispatcher: a chapter
        read aloud is a few thousand characters of text, which does not belong
        in a query string, and the answer is audio, which JSON would only
        base64 into something a third larger and no longer playable.
        """
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            return self._send(400, json.dumps({
                "ok": False, "error": f"that is not valid JSON: {e}",
            }).encode("utf-8"), "application/json; charset=utf-8")
        if not isinstance(body, dict):
            body = {}
        try:
            data = tts.synthesise(body.get("text", ""),
                                  body.get("voice") or tts.VOICE,
                                  body.get("speed", 1.0))
        except tts.Unavailable as exc:
            # 501, not 500: nothing here is broken, the voice simply is not
            # installed, and the front end falls back to the browser on seeing it.
            return self._send(501, json.dumps({
                "ok": False, "error": str(exc),
            }).encode("utf-8"), "application/json; charset=utf-8")
        except ValueError as exc:                  # nothing to say
            return self._send(400, json.dumps({
                "ok": False, "error": str(exc),
            }).encode("utf-8"), "application/json; charset=utf-8")
        except Exception as e:                       # synthesis blew up
            return self._send(500, json.dumps({
                "ok": False,
                "error": f"{type(e).__name__}: {e}",
            }).encode("utf-8"), "application/json; charset=utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Accept-Ranges", "none")
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            # Stopped part way through a chapter.  Expected: the client aborts
            # the fetch when you press stop, and that is not an error.
            pass

    def _serve_ai_stream(self, raw: bytes):
        """Answer one AI question as a server-sent-event stream.

        Off the JSON dispatcher on purpose: an answer arrives over tens of
        seconds and the reader should watch it arrive.  JSON can only be sent
        once and whole, so the transport here is SSE, which is the one thing a
        plain fetch() can consume incrementally without a second dependency.

        The first event carries the citations, before a single token is
        generated.  The reader therefore sees *what the answer will be grounded
        in* while the model is still thinking, and the source list cannot be
        assembled after the fact to match a reply the model already wrote.
        """
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            return self._send(400, json.dumps({
                "ok": False, "error": f"that is not valid JSON: {e}",
            }).encode("utf-8"), "application/json; charset=utf-8")
        if not isinstance(body, dict):
            body = {}

        self.close_connection = True
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()

        def frame(obj: dict) -> None:
            payload = ("data: " + json.dumps(obj, ensure_ascii=False)
                       + "\n\n").encode("utf-8")
            try:
                self.wfile.write(payload)
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError) as exc:
                raise _ClientGone() from exc

        try:
            provider, model = ai.resolve(body.get("provider") or None,
                                         body.get("model") or None)
            s = ai.get_settings()
            use_library = body.get("use_library")
            if use_library is None:
                use_library = s.get("use_library", True)
            use_mine = body.get("use_mine")
            if use_mine is None:
                use_mine = s.get("use_mine", True)
            scope = body.get("scope")
            if scope is None:
                scope = s.get("scope", "")
            context = _ai_context(body)
            semantic = body.get("semantic")
            if semantic is None:
                semantic = s.get("semantic", True)
            smart_query = body.get("smart_query")
            if smart_query is None:
                smart_query = s.get("smart_query", True)
            max_sources = int(body.get("max_sources") or s.get("max_sources", 8))

            # One stream, four shapes: a chat question, one study action over a
            # selection, one piece of sermon research over a passage, or one
            # question about a topic.  Each reuses the same builder the
            # non-streaming endpoint uses, so the two cannot drift into telling
            # the model different things.
            kind = (body.get("action") or "").strip()
            stats: dict = {}
            if kind == "topic":
                topic = body.get("topic", "")
                question = body.get("question", "")
                sources = ai.topic_sources(topic, max_sources=max(max_sources, 8))
                frame({"type": "sources", "citations": sources,
                       "provider": provider.id, "model": model,
                       "used_library": bool(use_library), "action": kind,
                       "topic": topic})
                msgs = ai.topic_messages(topic, question, sources,
                                         body.get("history") or [])
                usage_kind = "topic:ask"
            elif kind == "fact":
                term = body.get("term", "")
                question = body.get("question", "")
                lens = body.get("lens", "") or ""
                sources = ai.fact_sources(term, lens,
                                          max_sources=max(max_sources, 8))
                frame({"type": "sources", "citations": sources,
                       "provider": provider.id, "model": model,
                       "used_library": bool(use_library), "action": kind,
                       "term": term, "lens": lens})
                msgs = ai.fact_messages(term, question, sources, lens)
                usage_kind = "fact:ask"
            elif kind in ai.SERMON_ACTIONS:
                ref = body.get("ref", "")
                theme = body.get("theme", "")
                sources = ai.sermon_sources(ref, theme, bool(use_library),
                                            max(max_sources, 10))
                frame({"type": "sources", "citations": sources,
                       "provider": provider.id, "model": model,
                       "used_library": bool(use_library), "action": kind,
                       "sermon": kind, "ref": ref})
                msgs = ai.sermon_messages(kind, ref, theme, sources)
                usage_kind = f"sermon:{kind}"
            elif kind:
                text = body.get("text", "")
                label = body.get("label", "")
                target = body.get("target", "")
                sources = ai.action_sources(kind, text, label,
                                            bool(use_library), max_sources,
                                            use_mine=bool(use_mine),
                                            scope=scope or "",
                                            provider=provider,
                                            semantic=bool(semantic),
                                            smart_query=bool(smart_query))
                frame({"type": "sources", "citations": sources,
                       "provider": provider.id, "model": model,
                       "used_library": bool(use_library),
                       "used_mine": bool(use_mine), "scope": scope or "",
                       "semantic": bool(semantic) and provider.embeds,
                       "action": kind})
                msgs = ai.action_messages(kind, text, label, target, sources)
                usage_kind = f"action:{kind}"
            else:
                question = body.get("question", "")
                sources = ai.build_context(question, max_sources,
                                           use_library=bool(use_library),
                                           use_mine=bool(use_mine),
                                           scope=scope or "", context=context,
                                           provider=provider,
                                           semantic=bool(semantic),
                                           smart_query=bool(smart_query))
                frame({"type": "sources", "citations": sources,
                       "provider": provider.id, "model": model,
                       "used_library": bool(use_library),
                       "used_mine": bool(use_mine), "scope": scope or "",
                       "semantic": bool(semantic) and provider.embeds,
                       "has_context": bool(context)})
                msgs = ai.build_messages(question, body.get("history") or [],
                                         sources, context)
                usage_kind = "chat"
            # The call is written down whatever becomes of it.  A reader who
            # presses stop has still spent the tokens the provider already
            # generated, so an aborted stream is recorded as an incomplete call
            # rather than quietly dropped.
            answer: list[str] = []
            try:
                for delta in ai.stream(msgs, provider, model, stats=stats):
                    answer.append(delta)
                    frame({"type": "delta", "text": delta})
            except Exception:
                ai.record_usage(provider.id, model, usage_kind, stats, ok=False)
                raise
            ai.record_usage(provider.id, model, usage_kind, stats)
            # Which words of each source the answer leaned on.  It is sent
            # after the answer because it cannot be known before it: the
            # fragment is the part of the source that says what the answer
            # says.
            if answer and sources:
                try:
                    frags = ai.fragments("".join(answer), sources)
                except Exception:                        # noqa: BLE001
                    frags = []
                if frags:
                    frame({"type": "fragments", "fragments": frags})
            frame({"type": "done"})
        except _ClientGone:
            pass
        except Exception as e:                            # noqa: BLE001
            try:
                frame({"type": "error", "error": str(e),
                       "hint": getattr(e, "hint", "")})
            except _ClientGone:
                pass


    def _serve_file(self, name: str, params: dict):
        """Hand back one generated export as a download.

        Everything here is generated on demand from what is already installed,
        so there is no path on disk to escape into and nothing to confine: the
        route name selects a builder, the query says what to build.  The one
        thing taken from the request that reaches the filesystem is the download
        filename, and that is reduced to a safe basename -- a Content-Disposition
        header is attacker-controlled text, and "../../etc/passwd" or a newline
        in it is not something to pass through unexamined.
        """
        fn = FILE_ROUTES.get(name)
        if fn is None:
            return self._send(404, b"no such export", "text/plain")
        try:
            out = fn(params)
        except Exception as e:                       # a builder failed
            return self._send(500, str(f"{type(e).__name__}: {e}").encode(),
                              "text/plain")
        if not isinstance(out, tuple) or len(out) != 3:
            return self._send(500, b"that export produced nothing", "text/plain")
        body, filename, ctype = out
        if isinstance(body, str):
            body = body.encode("utf-8")
        fname = os.path.basename(str(filename or "export"))
        fname = re.sub(r"[^A-Za-z0-9._-]+", "-", fname).strip("-.") or "export"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Disposition",
                         f'attachment; filename="{fname}"')
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        if not self._guard():
            return
        u = urllib.parse.urlparse(self.path)
        path = u.path
        if path.startswith("/api/") and not self._csrf_guard():
            return
        params = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        if path == "/audio":
            return self._serve_audio(params)
        if path == "/print.css":
            # Served from the Python module rather than duplicated into
            # style.css: the browser's print path and the exported HTML have to
            # agree, and two copies of a stylesheet drift apart the moment one
            # of them is edited.
            body = publish.print_stylesheet().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/css; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        if path.startswith("/file/"):
            return self._serve_file(path[6:], params)
        if path.startswith("/api/"):
            out = route(path[5:], params)
            body = json.dumps(out, ensure_ascii=False, default=str).encode("utf-8")
            self._send(200, body, "application/json; charset=utf-8")
            return
        self._serve_static(path)

    def do_POST(self):
        if not self._guard() or not self._csrf_guard():
            return
        u = urllib.parse.urlparse(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        if u.path == "/tts":
            return self._serve_tts(raw)
        if u.path == "/api/ai/stream":
            return self._serve_ai_stream(raw)
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            # A body that says JSON and is not JSON is a mistake worth naming.
            # It used to be re-read as a query string, so `{"id": "x"` came
            # back as {"{\"id\": \"x\""} and the route then complained about a
            # missing field, pointing nowhere near the real problem.
            ctype = (self.headers.get("Content-Type") or "").lower()
            if "json" in ctype:
                self._send(400, json.dumps({
                    "ok": False,
                    "error": f"the request body is not valid JSON: {e}",
                }).encode("utf-8"), "application/json; charset=utf-8")
                return
            body = {k: v[0] for k, v in
                    urllib.parse.parse_qs(raw.decode("utf-8", "replace")).items()}
        if not isinstance(body, dict):
            body = {"value": body}
        out = route(u.path[5:] if u.path.startswith("/api/") else u.path, body)
        payload = json.dumps(out, ensure_ascii=False, default=str).encode("utf-8")
        self._send(200, payload, "application/json; charset=utf-8")

    def _serve_static(self, path: str):
        if path in ("/", ""):
            path = "/index.html"
        # module media (maps, images)
        m = re.match(r"^/media/([A-Za-z0-9._\-/]+)$", path)
        if m:
            rel = m.group(1)
            base = db.modules_dir().resolve()
            target = (base / rel).resolve()
            try:
                target.relative_to(base)
            except ValueError:
                self._send(403, b"forbidden", "text/plain")
                return
            if target.is_file():
                ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
                self._send(200, target.read_bytes(), ctype, cache=True)
                return
            self._send(404, b"not found", "text/plain")
            return
        target = (WEB_DIR / path.lstrip("/")).resolve()
        try:
            target.relative_to(WEB_DIR.resolve())
        except ValueError:
            self._send(403, b"forbidden", "text/plain")
            return
        if not target.is_file():
            self._send(404, b"not found", "text/plain")
            return
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",
                                                  "application/json"):
            ctype += "; charset=utf-8"
        try:
            data = target.read_bytes()
        except OSError:
            self._send(404, b"not found", "text/plain")
            return
        if target.name == "index.html":
            data = data.replace(b"__GBIBLE_CSRF_TOKEN__",
                                CSRF_TOKEN.encode("ascii"))
        self._send(200, data, ctype)


# -------------------------------------------------------------------- sync


def serve(host: str = "127.0.0.1", port: int = 8777) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    # The interval worker is started here rather than in the launcher so that
    # every way of starting the server gets it.  Sync is optional by design: if
    # it cannot start, the app opens and reads exactly as before.
    try:
        sync.start_worker()
    except Exception:
        pass
    return httpd
