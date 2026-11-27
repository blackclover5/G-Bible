"""Approved web research for the AI assistant.

The reader does not choose websites or pages. G-Bible carries a small, curated
list of study sites, and asks for permission for each question that would
benefit from the web. A yes authorizes one plan only. This module finds
the most relevant page on those sites and hands the text to the AI alongside
the reader's installed library.

The safety rules are unchanged from the earlier version and stay invisible to
the reader:

* Nothing is fetched until consent has been given.  Consent lives only in this
  process's memory, so restarting the app asks again.
* Only HTTPS, an exact host match, no credentials, no redirects, and a
  connection pinned to the DNS-verified public IP.
* Discovery happens on the built-in sites themselves: their own article URL
  shapes first, then their own search pages.  Links are accepted only from the
  built-in host being read.
* Remote text is labelled in the prompt as untrusted data, never instructions.
"""

from __future__ import annotations

import html
import http.client
import ipaddress
import re
import secrets
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

#: The only websites G-Bible will read for outside research.  `patterns` are
#: the site's own URL shapes (verified against the live sites), used to reach
#: the article a question names directly.  `search` is the site's own search
#: page, used as a fallback when the URL pattern does not match.
SITES: tuple[dict, ...] = (
    {"id": "aig", "label": "Answers in Genesis", "host": "answersingenesis.org",
     "topics": ("creation", "genesis", "flood", "noah", "ark", "evolution",
                "young earth", "age of the earth", "dinosaur", "fossil",
                "apologetics", "bible authority"),
     "patterns": ("https://answersingenesis.org/{slug}/",),
     "search": "https://answersingenesis.org/?s={q}",
     "sitemap": "https://a68201.sitemaphosting.com/3924992/sitemap1.xml",
     "sitemap_host": "a68201.sitemaphosting.com"},
    {"id": "gq", "label": "Got Questions", "host": "www.gotquestions.org",
     "topics": ("question", "jesus", "salvation", "bible", "god", "faith",
                "christian", "church", "doctrine", "sin", "heaven", "david",
                "bathsheba", "nathan", "baby", "infant", "child"),
     "patterns": ("https://www.gotquestions.org/{slug}.html",),
     "search": "https://www.gotquestions.org/search.html?search={q}",
     "sitemap": "https://www.gotquestions.org/sitemap.xml"},
    {"id": "tgc", "label": "The Gospel Coalition",
     "host": "www.thegospelcoalition.org",
     "topics": ("gospel", "jesus", "church", "theology", "pastor", "discipleship",
                "sermon", "christian living", "resurrection", "prayer", "faith"),
     "patterns": ("https://www.thegospelcoalition.org/article/{slug}/",),
     "search": "https://www.thegospelcoalition.org/?s={q}",
     "sitemap": "https://www.thegospelcoalition.org/article-sitemap.xml"},
    {"id": "bg", "label": "Bible Gateway", "host": "www.biblegateway.com",
     "topics": ("dictionary", "encyclopedia", "topical", "nave", "easton",
                "word study", "original language", "concordance", "strong",
                "lexicon", "hebrew", "greek", "interlinear", "definition",
                "meaning"),
     "patterns": (),
     "sitemap": "https://www.biblegateway.com/site-map/map-topical-1.xml"},
    {"id": "bo", "label": "Bible Odyssey", "host": "www.bibleodyssey.org",
     "topics": ("scholarship", "scholars", "archaeology", "ancient near east",
                "hebrew bible", "new testament", "genesis", "manuscript",
                "translation", "canon", "prophet", "paul", "temple",
                "psalms", "word study", "jesus", "history"),
     "patterns": ("https://www.bibleodyssey.org/articles/{slug}/",),
     "sitemap": "https://www.bibleodyssey.org/article-sitemap.xml"},
    {"id": "step", "label": "STEP Bible", "host": "www.stepbible.org",
     "topics": ("hebrew", "greek", "strong", "lexicon", "original language",
                "morphology", "concordance", "word study", "interlinear",
                "meaning", "word", "verses"),
     "patterns": ("https://www.stepbible.org/?q=meanings={slug}",),
     "sitemap": "https://www.stepbible.org/sitemap.xml"},
    {"id": "bp", "label": "Bible Project", "host": "bibleproject.com",
     "topics": ("bible project", "biblical theology", "gospel", "kingdom of god",
                "covenant", "sermon on the mount", "parables", "genesis",
                "exodus", "psalms", "prophets", "apocalypse", "baptism",
                "jesus", "hebrew", "greek", "word study", "book of"),
     "patterns": ("https://bibleproject.com/articles/{slug}/",),
     "sitemap": "https://bibleproject.com/en/sitemap.xml"},
)

MAX_SITES = 3
#: Bounded follow-up: read up to six pages, but never more than this many
#: requests per question.  Approved sites are still allowed sites; the cap and
#: the pause are about being a polite reader, not about distrust of the sites.
MAX_PAGES = 6
MAX_FETCHES = 14
FETCH_PAUSE = 0.35
#: A site may ask for a slower pace in its robots.txt.  Keep to it: one page
#: per question is small, but a stream of questions must not become a crawl.
SITE_PAUSE: dict[str, float] = {"www.biblegateway.com": 15.0}
_last_fetch: dict[str, float] = {}
MAX_QUERY = 160
MAX_BYTES = 3_000_000
MAX_INDEX_BYTES = 12_000_000       # a site's sitemap, read once per day
MAX_TEXT = 6000
TOKEN_TTL = 300
INDEX_TTL = 24 * 60 * 60
_PENDING: dict[str, dict] = {}
_DONE: dict[str, dict] = {}
_SESSION: dict[str, bool] = {"allowed": False}
_INDEX: dict[str, tuple[float, list[str]]] = {}

_HOST = re.compile(
    r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
    r"(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$")


# --------------------------------------------------------------------------
# Short-lived consent: memory only and consumed by the next plan.
# --------------------------------------------------------------------------

def consent_allowed() -> bool:
    return bool(_SESSION.get("allowed"))


def set_consent(allow: bool) -> bool:
    _SESSION["allowed"] = bool(allow)
    return consent_allowed()


def sites_view() -> list[dict]:
    return [{"id": s["id"], "label": s["label"], "host": s["host"]}
            for s in SITES]


def _choose_sites(query: str) -> list[dict]:
    q = " ".join(str(query or "").lower().split())
    scored = []
    for s in SITES:
        score = sum(1 for t in s["topics"] if t in q)
        scored.append((score, s))
    scored.sort(key=lambda x: -x[0])
    # There are only four sites.  Rank them so the most relevant is tried
    # first, but try all of them: a good page from a "lower ranked" site is
    # still better than no page at all.
    return [s for _score, s in scored]


# --------------------------------------------------------------------------
# URL and address checks
# --------------------------------------------------------------------------

def safe_url(url: str, allowed: set[str] | None = None) -> tuple[str | None, str]:
    allowed = allowed if allowed is not None else {s["host"] for s in SITES}
    raw = str(url or "").strip()
    try:
        u = urllib.parse.urlsplit(raw)
    except ValueError:
        return None, "not a URL"
    if u.scheme.lower() != "https":
        return None, "only https links can be fetched"
    if u.username or u.password:
        return None, "links with a username or password are refused"
    host = (u.hostname or "").lower().rstrip(".")
    if not host or host not in allowed:
        return None, "that website is not on the built-in list"
    try:
        port = u.port
    except ValueError:
        return None, "that link has an invalid port"
    if port not in (None, 443):
        return None, "only the standard https port is allowed"
    path = urllib.parse.quote(urllib.parse.unquote(u.path or "/"),
                              safe="/%:@&=+$,;~-._!")
    return urllib.parse.urlunsplit(("https", host, path or "/", u.query, "")), ""


def _public_ips(host: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except OSError:
        return []
    if not infos:
        return []
    out = []
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return []
        if not ip.is_global or ip.is_multicast:
            return []
        out.append(str(ip))
    return out


class _PinnedHTTPS(http.client.HTTPSConnection):
    """Connect to the address we checked, not a second DNS answer."""

    def __init__(self, host: str, pinned_ip: str, **kw):
        self._pinned_ip = pinned_ip
        super().__init__(host, **kw)

    def connect(self):
        self.sock = socket.create_connection(
            (self._pinned_ip, self.port), self.timeout, self.source_address)
        if self._tunnel_host:
            self._tunnel()
        # `server_hostname` only exists on newer Pythons; older releases keep
        # the SNI name in `host`.  Either way TLS is checked against the name,
        # not the pinned IP.
        hostname = getattr(self, "server_hostname", None) or self.host
        self.sock = self._context.wrap_socket(self.sock, server_hostname=hostname)


class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, pinned_ip: str):
        self._pinned_ip = pinned_ip
        super().__init__(context=ssl.create_default_context())

    def https_open(self, req):
        return self.do_open(
            lambda host, **kw: _PinnedHTTPS(host, self._pinned_ip, **kw), req)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code,
                                     "redirects are not followed", headers, fp)


def _get_raw(url: str, allowed: set[str],
             max_bytes: int = MAX_BYTES) -> tuple[bytes | None, str]:
    clean, err = safe_url(url, allowed)
    if not clean:
        return None, err
    host = urllib.parse.urlsplit(clean).hostname or ""
    ips = _public_ips(host)
    if not ips:
        return None, "that address is not a public website"
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), _NoRedirect(), _PinnedHTTPSHandler(ips[0]))
    # Several of these sites return 406 to a tool-like user agent, including
    # GotQuestions for its own sitemap.  A normal browser header is enough to
    # be served the public page; nothing is identifying or sent anywhere else.
    req = urllib.request.Request(clean, headers={
        "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
        "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
                   "text/plain;q=0.8,*/*;q=0.7"),
        "Accept-Language": "en-US,en;q=0.9",
    })
    try:
        with opener.open(req, timeout=12) as resp:
            if urllib.parse.urlsplit(resp.geturl()).hostname != host:
                return None, "the site redirected elsewhere"
            raw = resp.read(max_bytes + 1)
    except urllib.error.HTTPError as e:
        return None, f"the site returned {e.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return None, "could not reach that site: " + str(e)[:160]
    if len(raw) > max_bytes:
        return None, "that page is too large to read"
    return raw, ""


class _Text(HTMLParser):
    _SKIP = {"script", "style", "noscript", "svg", "iframe", "form"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title: list[str] = []
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        t = tag.lower()
        if t in self._SKIP:
            self._skip += 1
        elif t == "title":
            self._in_title = True
        elif t in ("p", "div", "br", "li", "h1", "h2", "h3", "tr"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        t = tag.lower()
        if t in self._SKIP and self._skip:
            self._skip -= 1
        elif t == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title.append(data)
        elif not self._skip:
            self.parts.append(data)


def _extract(raw: bytes, url: str) -> dict:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1", "replace")
    p = _Text()
    try:
        p.feed(text)
    except Exception:                                    # noqa: BLE001
        p = None
    if p is None:
        body = re.sub(r"<[^>]+>", " ", text)
        title = ""
    else:
        body = "".join(p.parts)
        title = " ".join("".join(p.title).split())
    body = html.unescape(body)
    lines = [" ".join(line.split()) for line in body.splitlines()]
    body = "\n".join(line for line in lines if line)
    return {"url": url, "title": title[:200], "text": body[:MAX_TEXT]}


# --------------------------------------------------------------------------
# Discovery: find the best page on each chosen site
# --------------------------------------------------------------------------

_STOP = {"a", "an", "and", "about", "are", "as", "at", "be", "by", "did",
         "do", "does", "for", "from", "how", "in", "is", "of", "on", "or",
         "the", "to", "was", "were", "what", "when", "where", "which", "who",
         "why", "with", "you", "your", "many", "much", "fit", "large",
         "small", "number", "total", "meaning", "definition", "though",
         "follow", "question", "up"}


def _slugs(query: str) -> list[str]:
    """URL-ready forms of the question, most specific first."""
    words = re.findall(r"[a-z0-9]+", str(query or "").lower())
    if not words:
        return []
    full = "-".join(words[:7])
    meaningful = [w for w in words if w not in _STOP]
    short = "-".join(meaningful[:5]) or full
    out = []
    for s in (full, short, "-".join(meaningful[:2]) or full):
        if s and s not in out:
            out.append(s)
    return out


def _load_index(site: dict) -> list[str]:
    """Article URLs from a site's sitemap, cached for a day in memory.

    A sitemap is a list of real page addresses.  Searching it locally avoids
    both search-engine bot challenges and the JavaScript-only result pages
    several of these sites use.  It is public index data, not reader data.
    """
    url = site.get("sitemap")
    if not url:
        return []
    now = time.time()
    cached = _INDEX.get(site["id"])
    if cached and now - cached[0] < INDEX_TTL:
        return cached[1]
    # Some sites host their sitemap on a separate index host.  It is read only
    # as index data; every article URL it names must still be on the site's own
    # host before it can be fetched.
    index_host = site.get("sitemap_host") or site["host"]
    raw, err = _get_raw(url, {index_host}, MAX_INDEX_BYTES)
    if not raw:
        return []
    out = []
    for loc in re.findall(r"<loc>([^<]+)</loc>", raw.decode("utf-8", "replace"),
                          re.IGNORECASE):
        clean, why = safe_url(loc.strip(), {site["host"]})
        if not clean or why:
            continue
        path = urllib.parse.urlsplit(clean).path
        # Video landing pages carry almost no prose once scripts are stripped;
        # the sitemap is used here as a list of readable articles.
        if any(x in path.lower() for x in (
                "/content_", "/questions_", "/search", "/sitemap",
                "/archive", "/top20", "/subscribe", "/donate", "/privacy",
                "/copyright", "/about", "/videos")):
            continue
        # A site whose article addresses live in the query string (STEP Bible
        # uses `?q=...meanings=Jacob`) has an empty path.  It is still a real
        # article, not the home page: keep it when it carries a query.
        parts = urllib.parse.urlsplit(clean)
        if not parts.path.strip("/") and not parts.query:
            continue
        if clean not in out:
            out.append(clean)
    _INDEX[site["id"]] = (now, out)
    return out


#: Words that point at the same article even when they are not in its URL.
_SYNONYMS = {
    "friday": ("crucifixion", "crucified", "good"),
    "wednesday": ("crucifixion", "crucified", "three", "days"),
    "died": ("crucifixion", "crucified", "death", "tomb"),
    "die": ("crucifixion", "crucified", "death", "tomb"),
}


def _rank_index(site: dict, query: str, limit: int = 4) -> list[str]:
    """Best-matching article URLs from the site's own sitemap."""
    words = {w for w in re.findall(r"[a-z0-9]+", query.lower())
             if len(w) > 2 and w not in _STOP}
    if not words:
        return []
    expanded = set(words)
    for w in words:
        expanded.update(_SYNONYMS.get(w, ()))
    # "jesus" appears in hundreds of URLs; "friday" in a handful.  A rare
    # word that actually appears in the question is worth far more than a
    # common one, or a generic article about the person wins every time.
    # Three tiers, because two were not enough: a question like "what does
    # the Bible say about love" matched "bible" and "love" equally, so a
    # sitemap ordered alphabetically picked the broad "Bible" entry.  The
    # broadest words now score least, so the specific topic wins the tie.
    generic = {"jesus", "god", "christ", "bible", "christian", "church",
               "people", "life", "who", "what", "why", "how", "did", "does",
               "was", "were", "say", "says", "mean", "means"}
    common = {"love", "sin", "faith", "man", "word", "name", "meaning"}
    def weight(w):
        if w in generic:
            return 1
        if w in common:
            return 5
        return 10

    scored = []
    for url in _load_index(site):
        parts = urllib.parse.urlsplit(url)
        # Most sitemaps end article URLs in '/'.  Taking the last split of the
        # raw path gives '' for every one of those, so no word ever matched and
        # these sites silently contributed nothing (GotQuestions ends in .html
        # and was the only site that worked).  Drop trailing slashes first.
        path = parts.path.lower()
        query_part = parts.query.lower()
        slug = path.rstrip("/").rsplit("/", 1)[-1]
        if not slug.strip("-/"):
            # The words can live in the query instead of the path (STEP Bible
            # addresses pages as ?q=...meanings=Jacob).  Rank those too.
            slug = query_part
        # Rank on the whole address, not just the last segment.  A site may put
        # the subject in a parent segment and the dictionary name last, as Bible
        # Gateway does with /topical/Love/Nave; tokenising only "nave" would
        # never match the word the reader asked about.
        toks = set(re.findall(r"[a-z0-9]+", path + " " + query_part))
        direct = toks & words
        extra = (toks & expanded) - direct
        if not direct and not extra:
            continue
        score = sum(weight(w) for w in direct) + 6 * len(extra)
        # A phrase kept in its original order is a stronger signal than a bag
        # of words: "who-is-jesus" beats "jesus-is-who".
        if len(words) > 1:
            ordered = "-".join(re.findall(r"[a-z0-9]+", query.lower())[:5])
            if ordered and ordered in slug:
                score += 20
        scored.append((score, url))
    scored.sort(key=lambda x: -x[0])
    return [url for _score, url in scored[:limit]]


def _candidates(site: dict, query: str) -> list[str]:
    """URLs to try on one site, before falling back to its own search page."""
    out = []
    for url in _rank_index(site, query):
        if url not in out:
            out.append(url)
    for slug in _slugs(query):
        for pattern in site["patterns"]:
            url = pattern.replace("{slug}", slug)
            clean, err = safe_url(url, {site["host"]})
            if clean and not err and clean not in out:
                out.append(clean)
    search = site.get("search")
    if search:
        url = search.replace("{q}", urllib.parse.quote_plus(
            " ".join(str(query or "").split())[:MAX_QUERY]))
        clean, err = safe_url(url, {site["host"]})
        if clean and not err and clean not in out:
            out.append(clean)
    return out


class _Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href = ""
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            self._href = dict(attrs).get("href") or ""
            self._text = []

    def handle_data(self, data):
        if self._href:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self._href:
            self.links.append((self._href, " ".join("".join(self._text).split())))
            self._href = ""
            self._text = []


def _site_links(raw: bytes, host: str) -> list[str]:
    """Article links on a site's own search page, filtered to that host."""
    parser = _Links()
    try:
        parser.feed(raw.decode("utf-8", "replace"))
    except Exception:                                    # noqa: BLE001
        return []
    out = []
    for href, text in parser.links:
        if href.startswith("//"):
            href = "https:" + href
        elif href.startswith("/"):
            href = "https://" + host + href
        clean, err = safe_url(href, {host})
        if err or not clean:
            continue
        path = urllib.parse.urlsplit(clean).path
        if len(path.strip("/")) < 8 or len(text) < 12:
            continue
        if clean not in out:
            out.append(clean)
    return out


_BLOCKED = re.compile(r"human verification|captcha|are you a robot|access denied",
                      re.IGNORECASE)


def _looks_real(out: dict) -> bool:
    text = out.get("text") or ""
    return len(text) >= 250 and not _BLOCKED.search(text + " " + (out.get("title") or ""))


def _answer_relevant(out: dict, query: str) -> bool:
    """Reject pages that are readable but do not address this question.

    Page discovery can find a generic article on the right site. Require topic
    words in the actual article (and at least one in its title or URL), not
    merely a successful fetch. Count questions also need a count-like answer
    in the page text. This intentionally errs toward omitting a weak web source.
    """
    def words(text: str) -> set[str]:
        found = set(re.findall(r"[a-z0-9]+", (text or "").lower()))
        out_words = set(found)
        if "arc" in found:
            out_words.add("ark")
        for word in found:
            if len(word) > 4 and word.endswith("ies"):
                out_words.add(word[:-3] + "y")
            elif len(word) > 5 and word.endswith("ing"):
                out_words.add(word[:-3])
            elif len(word) > 4 and word.endswith("ed"):
                out_words.add(word[:-2])
                # Preserve the silent-e verb root: created -> create. The
                # simple suffix form above produces "creat", which prevented
                # a direct match for queries about creation.
                out_words.add(word[:-1])
            elif len(word) > 4 and word.endswith("s"):
                out_words.add(word[:-1])
        # A useful page may answer with a near-equivalent term rather than
        # repeat the reader's wording (baby/child, killed/died, eat/feeding).
        # Expand in both directions so the gate checks meaning-bearing terms
        # without treating an unrelated page as relevant on generic words.
        aliases = {
            "create": {"created", "creation", "creating"},
            "creation": {"create", "created", "creating"},
            "sermon": {"teaching", "teach", "taught"},
            "teach": {"sermon", "teaching", "taught"},
            "mount": {"kingdom", "teaching", "teach", "taught"},
            "baby": {"child", "infant", "newborn", "son", "daughter"},
            "child": {"baby", "infant", "newborn", "son", "daughter"},
            "kill": {"killed", "die", "died", "death", "dead", "slay", "slain"},
            "die": {"kill", "killed", "died", "death", "dead", "slay", "slain"},
            "death": {"kill", "killed", "die", "died", "dead", "slay", "slain"},
            "eat": {"food", "feed", "feeding", "fed", "eaten", "nourish"},
            "food": {"eat", "feed", "feeding", "fed", "eaten", "nourish"},
        }
        for word in tuple(out_words):
            for root, variants in aliases.items():
                if word == root or word in variants:
                    out_words.add(root)
                    out_words.update(variants)
        return out_words

    terms = {w for w in words(query) if len(w) > 2 and w not in _STOP}
    if not terms:
        return False
    # Keep named subjects in the title check. A generic page about babies may
    # mention God and death, but it does not answer a question about David's
    # child unless the page is actually about David or the event in question.
    generic_names = {"what", "who", "whom", "where", "when", "why", "how",
                     "does", "did", "can", "could", "would", "should", "god",
                     "lord", "bible", "follow", "question"}
    named = {w for w in re.findall(r"\b[A-Z][A-Za-z]{2,}\b", query)
             if w.lower() not in generic_names}
    named_terms = words(" ".join(named))
    title_url = words((out.get("title") or "") + " " + (out.get("url") or ""))
    if named_terms and not (named_terms & title_url):
        return False
    body = words(out.get("text") or "")
    matched = terms & body
    if not matched or not (terms & title_url):
        return False
    required = max(1, (len(terms) * 3 + 4) // 5)
    if len(matched) < required:
        return False
    q = (query or "").lower()
    if re.search(r"\bhow many\b", q):
        count_words = r"(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|hundred|thousand|pair|pairs)"
        subject_words = r"(?:animals?|beasts?|creatures?)"
        sentences = re.split(r"(?<=[.!?])\s+", out.get("text") or "")
        has_answer = any(
            re.search(count_words, sentence, re.IGNORECASE)
            and re.search(subject_words, sentence, re.IGNORECASE)
            for sentence in sentences)
        if not has_answer:
            return False
    return True


# --------------------------------------------------------------------------
# One-use tokens
# --------------------------------------------------------------------------

def _query_variants(query: str) -> list[str]:
    """The question as asked, then one narrower formulation.

    The second pass is how a thin first search gets a follow-up: it keeps only
    the distinctive content words, the same trick the sitemap ranker uses, and
    searches the same approved sites again.  There are never more than two
    variants, and the fetch budget below bounds the whole run.
    """
    out = [query]
    words = re.findall(r"[^\W\d_]+", (query or "").lower())
    seen: set[str] = set()
    kept: list[str] = []
    for w in words:
        if len(w) < 4 or w in _STOP or w in seen:
            continue
        seen.add(w)
        kept.append(w)
    narrow = " ".join(kept[:5])
    if narrow and narrow.lower() != query.strip().lower():
        out.append(narrow)
    return out


def _prune(store: dict) -> None:
    now = time.time()
    for k in [k for k, v in store.items() if v.get("expires", 0) < now]:
        store.pop(k, None)
    while len(store) > 60:
        store.pop(next(iter(store)))


def plan(query: str) -> dict:
    """Create a token naming the question and the sites to search.  No fetch."""
    if not consent_allowed():
        return {"ok": False, "error": "Outside research has not been approved."}
    # A yes in the UI is for the question currently being asked, not a blanket
    # session setting. Consume it before creating the plan so later questions
    # need a fresh, visible choice.
    set_consent(False)
    _prune(_PENDING)
    _prune(_DONE)
    q = " ".join(str(query or "").split())[:MAX_QUERY]
    if re.search(r"\barc\b", q, re.IGNORECASE) and re.search(
            r"\banimals?\b|\bbeasts?\b|\bcreatures?\b", q, re.IGNORECASE):
        q = re.sub(r"\barc\b", "Ark", q, flags=re.IGNORECASE)
    if not q:
        return {"ok": False, "error": "No question to research."}
    chosen = _choose_sites(q)
    token = secrets.token_urlsafe(24)
    _PENDING[token] = {"query": q, "sites": chosen,
                       "allowed": {s["host"] for s in SITES},
                       "expires": time.time() + TOKEN_TTL}
    return {"ok": True, "token": token,
            "sites": [{"label": s["label"], "host": s["host"]} for s in chosen]}


def take_plan(token: str) -> dict:
    _prune(_PENDING)
    entry = _PENDING.pop(str(token or ""), None)
    if not entry:
        raise ValueError("that request has expired")
    return entry


def run(token: str) -> dict:
    """Consent has been given: read the best pages from the approved sites.

    Public web search engines now serve bot challenges, so discovery goes to
    the study sites themselves.  A first pass uses the question as asked; if it
    found little, one narrower pass follows against the same approved sites.
    Both the number of pages and the total number of requests are capped, and
    requests are spaced out -- a follow-up is deeper research, not a flood of
    traffic.  A site that blocks automated reading is reported by name rather
    than failing silently.
    """
    entry = take_plan(token)
    q, chosen = entry["query"], entry["sites"]
    results: list[dict] = []
    failures: set[str] = set()
    used_sites: set[str] = set()
    tried: set[str] = set()
    attempts = 0

    def fetch(url: str) -> tuple[bytes | None, str]:
        nonlocal attempts
        if url in tried or attempts >= MAX_FETCHES:
            return None, "request budget spent"
        tried.add(url)
        attempts += 1
        if attempts > 1:
            time.sleep(FETCH_PAUSE)
        # Respect a host's published crawl delay as well as the global pause.
        host = urllib.parse.urlsplit(url).hostname or ""
        pause = SITE_PAUSE.get(host, 0.0)
        if pause:
            wait = pause - (time.time() - _last_fetch.get(host, 0.0))
            if wait > 0:
                time.sleep(wait)
        _last_fetch[host] = time.time()
        return _get_raw(url, entry["allowed"])

    for variant in _query_variants(q):
        if len(results) >= MAX_PAGES or attempts >= MAX_FETCHES:
            break
        for site in chosen:
            if len(results) >= MAX_PAGES or attempts >= MAX_FETCHES:
                break
            if site["id"] in used_sites:
                continue
            found = None
            tried_here = 0
            for url in _candidates(site, variant):
                if tried_here >= 5 or attempts >= MAX_FETCHES:
                    break
                if url in tried:
                    continue
                tried_here += 1
                raw, err = fetch(url)
                if not raw:
                    continue
                # A search page is a source of links, not an answer.  Pick an
                # article from it, then read that.
                if site.get("search") and url.split("?")[0] == site["search"].split("?")[0]:
                    for link in _site_links(raw, site["host"])[:2]:
                        article, aerr = fetch(link)
                        if not article:
                            continue
                        out = _extract(article, link)
                        if _looks_real(out) and _answer_relevant(out, q):
                            found = out
                            break
                    if found:
                        break
                    continue
                out = _extract(raw, url)
                if _looks_real(out) and _answer_relevant(out, q):
                    found = out
                    break
            if found:
                found.update({"ok": True, "host": site["host"],
                              "label": site["label"], "why": "best match on this site"})
                results.append(found)
                used_sites.add(site["id"])
            else:
                failures.add(site["label"])

    failed = sorted(failures)
    if not results:
        detail = ""
        if failed:
            detail = " Could not read: " + ", ".join(failed) + "."
        return {"ok": False,
                "error": "No approved page could be read." + detail,
                "results": []}
    out_token = secrets.token_urlsafe(24)
    _prune(_DONE)
    _DONE[out_token] = {"results": results, "expires": time.time() + TOKEN_TTL}
    return {"ok": True, "results": results, "token": out_token,
            "failed": failed}


def take_results(token: str) -> list[dict]:
    if not token:
        return []
    entry = _DONE.pop(str(token), None)
    return entry["results"] if entry else []


def as_sources(results: list[dict]) -> list[dict]:
    out = []
    for r in results or []:
        if not isinstance(r, dict) or not r.get("ok") or not (r.get("text") or "").strip():
            continue
        out.append({
            "n": 0,
            "module_id": "web:" + (r.get("host") or ""),
            "module_name": r.get("label") or r.get("host") or "Website",
            "label": r.get("title") or r.get("url") or "",
            "title": r.get("title") or "",
            "type": "Web",
            "text": (r.get("text") or "")[:MAX_TEXT],
            "url": r.get("url") or "",
            "external": True,
        })
    return out
