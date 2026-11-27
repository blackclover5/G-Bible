"""API for session-consented web research.

Consent is kept only in the server process, so closing G-Bible and opening it
again asks the reader once more.  `plan` names the sites without fetching;
`run` does the discovery and reading; the AI call receives a one-use result
token, so outside text cannot reach the model without that consent.
"""

from .common import *          # noqa: F401,F403  (endpoint, _ok)
from ... import webresearch


@endpoint("webresearch/consent")
def _consent(parts, q):
    if "allow" in q:
        allowed = webresearch.set_consent(
            str(q.get("allow")).strip().lower() in ("1", "true", "yes", "on"))
        return _ok(allowed=allowed)
    return _ok(allowed=webresearch.consent_allowed())


@endpoint("webresearch/sites")
def _sites(parts, q):
    return _ok(sites=webresearch.sites_view())


@endpoint("webresearch/plan")
def _plan(parts, q):
    return webresearch.plan(q.get("query", ""))


@endpoint("webresearch/run")
def _run(parts, q):
    return webresearch.run(q.get("token", ""))
