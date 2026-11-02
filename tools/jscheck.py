"""Static checks on the front end.

The bugs this catches are the ones that do not show up as a Python error.  A
`$('#thing')` for an element that is not in the page returns null, and the line
after it throws something unrelated ten frames away; `App.showPane(...)` on an
object that has no `showPane` throws "is not a function" only when that path is
taken.  Both happened repeatedly here, and both were found by clicking, not by
running the tests.

So: parse every *.js file in gbible/web, collect the object literals, and check
three things.

    * an object does not define the same name twice -- the second silently wins
    * a call to NAME.method() names a method NAME actually has
    * every $('...') and api('...') refers to something that exists, in the
      markup and in the route table respectively

Requires `esprima`, which is in the Playwright venv rather than the system
Python.  Skipped, clearly, when it is not importable.
"""

from __future__ import annotations

import collections
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JS_FILES = sorted((ROOT / "gbible" / "web").glob("*.js"))
HTML = ROOT / "gbible" / "web" / "index.html"
ROUTE_FILES = sorted((ROOT / "gbible" / "server" / "routes").glob("*.py"))


def redeclarations(tree) -> list[str]:
    """`const x` twice in one scope, and `let` twice.

    esprima parses this file happily and the browser refuses to run it, because
    redeclaring a lexical binding is an *early* error: it belongs to the
    language's static semantics, and a parser whose only job is to build a tree
    has no reason to look.  That gap is not theoretical -- `const langs` was
    added to a function that already declared one, and the whole application
    stopped working, with nothing but "Identifier 'langs' has already been
    declared" in the console.  Every id and every endpoint in this file
    resolved perfectly while the app was dead.

    So walk the scopes and count.  `var` is deliberately not reported:
    redeclaring a `var` is legal, and reporting it would be noise.
    """
    problems: list[str] = []

    def lexical_names(block) -> dict[str, int]:
        """How many times each lexical name is bound directly in this block.

        Only the statements immediately in the block, so `let` in a nested
        block or inside a nested function is a different binding -- which is
        legal, and reporting it would be noise of a different kind.
        """
        counts: dict[str, int] = {}
        for st in getattr(block, "body", []) or []:
            if getattr(st, "type", "") != "VariableDeclaration":
                continue
            if getattr(st, "kind", "var") not in ("const", "let"):
                continue
            for d in st.declarations:
                name = getattr(getattr(d, "id", None), "name", None)
                if name:
                    counts[name] = counts.get(name, 0) + 1
        return counts

    def check(block):
        for name, n in lexical_names(block).items():
            if n > 1:
                line = getattr(getattr(block, "loc", None), "start", None)
                problems.append(
                    f"line {getattr(line, 'line', '?')}: '{name}' is declared "
                    f"with const/let {n} times in one scope, which the browser "
                    f"rejects before running any of this file")

    def walk(node):
        t = getattr(node, "type", "")
        if t in ("FunctionDeclaration", "FunctionExpression",
                 "ArrowFunctionExpression"):
            body = getattr(node, "body", None)
            if getattr(body, "type", "") == "BlockStatement":
                walk(body)
            elif body is not None:
                walk(body)
            return
        if t == "BlockStatement":
            check(node)
            for st in getattr(node, "body", []) or []:
                walk(st)
            return
        if t == "ForStatement" or t == "ForOfStatement" or t == "ForInStatement":
            init = getattr(node, "init", None) or getattr(node, "left", None)
            for key in ("init", "left", "right", "test", "update", "body"):
                v = getattr(node, key, None)
                if v is None:
                    continue
                if hasattr(v, "type"):
                    walk(v)
                elif isinstance(v, list):
                    for item in v:
                        if hasattr(item, "type"):
                            walk(item)
            return
        if t == "SwitchCase":
            counts: dict[str, int] = {}
            for st in getattr(node, "consequent", []) or []:
                if getattr(st, "type", "") == "VariableDeclaration" and \
                        getattr(st, "kind", "var") in ("const", "let"):
                    for d in st.declarations:
                        nm = getattr(getattr(d, "id", None), "name", None)
                        if nm:
                            counts[nm] = counts.get(nm, 0) + 1
            for nm, n in counts.items():
                if n > 1:
                    problems.append(
                        f"line {getattr(getattr(node, 'loc', None), 'start', None) and node.loc.start.line}: "
                        f"'{nm}' is declared {n} times across the cases of one "
                        f"switch, which the browser rejects")
            for st in getattr(node, "consequent", []) or []:
                walk(st)
            return
        for key, val in list(getattr(node, "__dict__", {}).items()):
            if key in ("loc", "range", "type"):
                continue
            if isinstance(val, list):
                for v in val:
                    if hasattr(v, "type"):
                        walk(v)
            elif hasattr(val, "type"):
                walk(val)

    check(tree)
    for st in getattr(tree, "body", []) or []:
        walk(st)

    seen: set[str] = set()
    out: list[str] = []
    for pr in problems:
        key = pr.split("'")[1] if "'" in pr else pr
        if key not in seen:
            seen.add(key)
            out.append(pr)
    return out


def parse_js(esprima, src: str):
    """esprima.parseScript, tolerating regex syntax it is too old to know.

    esprima 4.0.1 predates ES2018, so `/[\\p{L}\\p{N}']/u` -- Unicode property
    escapes, in every modern browser -- comes back as "Invalid regular
    expression". That is the parser being behind the language, not the file
    being wrong, and letting it fail outright meant the whole check reported
    one line of noise and none of the findings it exists for: duplicate keys,
    calls to methods an object does not have, ids that do not exist.

    So parse the real source first. Only if that fails, retry with the ES2018
    regex forms and simple optional property access swapped for equivalents
    esprima accepts. The tree is used purely for structure -- which keys an
    object literal has, which method names are called, where each statement is
    -- and none of that depends on these syntax forms. Anything that still fails
    to parse is reported from the original source, so a genuine syntax error is
    never disguised as a parser limitation.
    """
    try:
        return esprima.parseScript(src, loc=True)
    except Exception as first:
        patched = _ES2018_RE.sub(_plain_regex, src)
        patched = re.sub(r"\?\.(?=[A-Za-z_$])", ".", patched)
        if patched == src:
            raise first
        try:
            return esprima.parseScript(patched, loc=True)
        except Exception:
            raise first


def _plain_regex(m: re.Match) -> str:
    """A stand-in for one ES2018 regex form, spelled so esprima accepts it."""
    return m.group(0).replace("\\p{", "x").replace("(?<", "(?:")


# \\p{...} property escapes and (?<name>...) named groups.
_ES2018_RE = re.compile(r"\\p\{[^}]*\}|\(\?<[A-Za-z_$][\w$]*>")


def _collect_assigned(node, out: set) -> None:
    """Every `X.prop = ...` target in the file, so run-time hooks count as defined."""
    if getattr(node, "type", "") == "AssignmentExpression":
        left = getattr(node, "left", None)
        if (getattr(left, "type", "") == "MemberExpression"
                and getattr(getattr(left, "object", None), "type", "") == "Identifier"
                and getattr(left.property, "name", None)):
            out.add(left.property.name)
    for v in list(vars(node).values()):
        if isinstance(v, list):
            for x in v:
                if hasattr(x, "type"):
                    _collect_assigned(x, out)
        elif hasattr(v, "type"):
            _collect_assigned(v, out)


def run() -> str:
    try:
        import esprima
    except ImportError:
        return "SKIP"

    files = JS_FILES
    srcs = {f: f.read_text(encoding="utf-8") for f in files}
    src = "\n".join(srcs.values())
    html = HTML.read_text(encoding="utf-8")
    trees = {}
    for f, s in srcs.items():
        try:
            trees[f] = parse_js(esprima, s)
        except Exception as e:
            return f"FAIL\n    - {f.name} does not parse: {type(e).__name__}: {e}"

    # --- redeclarations per file
    redecl_problems: list[str] = []
    for f, t in trees.items():
        for pr in redeclarations(t):
            redecl_problems.append(f"{f.name}: {pr}")

    # --- the top-level `const NAME = { ... }` objects the app is built from
    objs: dict[str, set] = {}
    duplicate: dict[str, list] = {}
    for f, t in trees.items():
        for node in t.body:
            if getattr(node, "type", "") != "VariableDeclaration":
                continue
            for d in node.declarations:
                if not (d.id and d.id.name and d.init
                        and getattr(d.init, "type", "") == "ObjectExpression"):
                    continue
                keys = []
                for p in d.init.properties:
                    k = p.key.name if p.key.type == "Identifier" else getattr(p.key, "value", None)
                    if k:
                        keys.append(k)
                for k, c in collections.Counter(keys).items():
                    if c > 1:
                        duplicate.setdefault(d.id.name, []).append(k)
                if d.id.name in objs:
                    objs[d.id.name] |= {k for k in keys}
                else:
                    objs[d.id.name] = {k for k in keys}

    # --- NAME.method() where NAME is one of those objects
    missing: dict[str, set] = collections.defaultdict(set)

    assigned_props: set[str] = set()
    for t in trees.values():
        for node in t.body:
            _collect_assigned(node, assigned_props)

    def walk(n):
        t = getattr(n, "type", "")
        if t == "CallExpression":
            c = n.callee
            if (getattr(c, "type", "") == "MemberExpression"
                    and getattr(c.object, "type", "") == "Identifier"):
                base, prop = c.object.name, getattr(c.property, "name", None)
                if base in objs and prop and prop not in objs[base]:
                    if prop not in ("then", "catch", "finally", "length") \
                            and prop not in assigned_props:
                        missing[base].add(prop)
        for k, v in vars(n).items():
            if k in ("loc", "range", "regex"):
                continue
            if isinstance(v, list):
                for x in v:
                    if hasattr(x, "type"):
                        walk(x)
            elif hasattr(v, "type"):
                walk(v)

    for t in trees.values():
        for node in t.body:
            walk(node)

    problems: list[str] = []
    for obj, names in sorted(duplicate.items()):
        problems.append(f"{obj} defines {', '.join(sorted(set(names)))} twice; "
                        f"the second silently replaces the first")
    for obj, names in sorted(missing.items()):
        problems.append(f"{obj} is called with methods it does not define: "
                        + ", ".join(sorted(names)))

    ids_in_html = set(re.findall(r'\bid="([^"]+)"', html))
    ids_made = set(re.findall(r'\bid="([A-Za-z0-9_-]+)"', src))
    ids_made |= set(re.findall(r"\.id\s*=\s*'([A-Za-z0-9_-]+)'", src))
    ids_made |= set(re.findall(r'\bid="([A-Za-z0-9_-]*)-?\'\s*\+', src))
    ids_made |= set(re.findall(r"\b(?:sel|row|opt|field)\(\s*'([A-Za-z0-9_-]+)'", src))
    known = ids_in_html | ids_made
    wanted = set(re.findall(r"\$\(\s*'#([A-Za-z0-9_-]+)'\s*\)", src))
    missing_ids = sorted(wanted - known)
    if missing_ids:
        problems.append("app.js selects ids that exist neither in index.html nor "
                        "anywhere in the script: " + ", ".join(missing_ids))
    templates = set(m for m in re.findall(
        r"\$\(\s*'#([A-Za-z0-9_-]+)-[^']*\$\{", src) if m not in known)
    templates |= set(m for m in re.findall(
        r"\$\(\s*'#([A-Za-z0-9_-]+)-'\s*\+", src) if m not in known)

    def stem_covered(t: str) -> bool:
        if t in known or (t + "-") in known:
            return True
        return any(i.startswith(t + "-") for i in ids_in_html)
    templates = sorted(t for t in templates if not stem_covered(t))
    if templates:
        problems.append("app.js builds ids from a template whose stem is never "
                        "defined: " + ", ".join(templates))
    routes = set()
    for route_file in ROUTE_FILES:
        route_source = route_file.read_text(encoding="utf-8")
        for m in re.finditer(r'@endpoint\("([^"]+)"\)', route_source):
            routes.add(m.group(1))
    called = set(re.findall(r"api\(\s*'([^']+)'", src))
    called |= set(re.findall(r'post\(\s*\'([^\']+)\'', src))
    unknown = sorted(p for p in called if p not in routes and "/" in p)
    if unknown:
        problems.append("app.js calls endpoints that are not registered: "
                        + ", ".join(unknown))

    problems.extend(lock_check())
    problems.extend(redecl_problems)
    if problems:
        return "FAIL\n    - " + "\n    - ".join(problems)
    return (f"{len(objs)} objects, {len(wanted)} ids, {len(called)} api calls, "
            f"all resolved")


def lock_check() -> list[str]:
    """Find calls that take _job_lock while it is already held.

    `threading.Lock` is not reentrant, so a helper that acquires it called from
    inside `with _job_lock:` deadlocks the request that made the call -- and the
    symptom is a page sitting on "starting" for ever rather than an error.  That
    is exactly what happened here when the job registry started pruning.

    Walked with ast rather than by counting indentation: a comment or a blank
    line at a deeper indent does not close a block, and a textual scan reported
    five deadlocks where there were none.
    """
    import ast as _ast
    tree = _ast.parse(
        (ROOT / "gbible" / "server" / "routes" / "common.py").read_text(
            encoding="utf-8"))
    takers = ("_remember_job", "_prune_jobs")
    out: list[str] = []

    def called(node) -> list[str]:
        """Names of the lock-taking helpers called anywhere in this subtree."""
        found = []
        for sub in _ast.walk(node):
            if isinstance(sub, _ast.Call) and isinstance(sub.func, _ast.Name) \
                    and sub.func.id in takers:
                found.append(sub.func.id)
        return found

    def scan(node, inside: list[int] | None) -> None:
        if inside is not None:
            for name in called(node):
                out.append(
                    f"line {inside[0]}: {name}() is reached inside "
                    f"'with _job_lock' opened there, which deadlocks -- the lock "
                    f"is not reentrant")
            return
        for child in _ast.iter_child_nodes(node):
            if isinstance(child, _ast.With):
                items = [ast_name(i.context_expr) for i in child.items]
                if "_job_lock" in items:
                    scan(child, [child.lineno])
                else:
                    scan(child, None)
            else:
                scan(child, None)

    def ast_name(node):
        if isinstance(node, _ast.Call):
            return ast_name(node.func)
        if isinstance(node, _ast.Attribute):
            return ast_name(node.value)
        if isinstance(node, _ast.Name):
            return node.id
        return None

    scan(tree, None)
    return out