**Security Policy**
G-Bible is an offline-first, local-only Bible study application. There is no account, no server-side service and no telemetry, so the security surface is small — but your study data, notes and any API keys you add are personal, and we take their protection seriously.
**Supported Versions**
Security fixes are made against the latest stable release. Older releases may be left behind when a newer one changes the backup or database format.
Version	Supported
1.0.x	:white_check_mark:
0.9.x	:x:
< 0.9	:x:
The version currently shipped is 1.0.3 (see pyproject.toml). If you are running an older release, update through Settings → About before reporting an issue, and check that the problem still occurs.

**Reporting a Vulnerability**
Please do not open a public GitHub issue for a security vulnerability. Public issues can expose the problem before a fix is available.
Report it privately instead, using one of these routes:
GitHub private vulnerability reporting (preferred): open the project's Security advisories page and submit a report. Only maintainers can see it until it is published.
If that feature is unavailable, contact the maintainer privately through GitHub (the account listed in the repository) and ask for a private channel.
Include as much of the following as you can:
A description of the issue and its impact (what an attacker could do).
The G-Bible version, operating system and how you installed the app (Flatpak, source, or an in-app update).
Step-by-step reproduction instructions, and a proof of concept if you have one.
Whether the issue needs network access, a malicious module file, a crafted .gbz backup, or local access to the machine.
Any suggested fix, if you have one.
Please give maintainers a reasonable opportunity to investigate and release a fix before disclosing the issue publicly.
What to expect

**Acknowledgement**: within about 7 days of a private report.

**Updates**: at least every 14 days while the report is being investigated, even if there is no new finding yet.
If accepted: we will confirm the issue, agree on a disclosure timeline, prepare a fix, and credit you in the release notes or advisory if you wish. We will publish a GitHub Security Advisory alongside the fixed release.
If declined: we will explain why — for example, if the behaviour is intentional, requires an already-compromised machine, or is outside the app's threat model — and let you appeal with more context.

**Severity**: we will assess impact using common-sense criteria (exposure of notes, keys or backup contents; code execution; cross-origin or local server access) rather than a formal CVSS score.

**Scope and threat model**

G-Bible runs on your own machine and serves its interface over a local loopback address (by default 127.0.0.1:8777). Reports in scope include:
Vulnerabilities in the local web server, request handling and static file serving (for example, path traversal or serving files outside data/).
Unsafe handling of untrusted module/resource files, OSIS or other imported markup, and crafted .gbz backup archives on restore.
Exposure of API keys in data/api-credentials.json, logs, error reports or the user interface.
Injection issues in rendered study content, search results, notes or logs.
Problems with WebDAV/Nextcloud sync, update checks, or in-place update file handling (for example, unverified downloads or unsafe file replacement).

**Out of scope:** issues that require physical or already-administrative access to the user's machine, third-party AI provider or Store repository security, and vulnerabilities in dependencies that have not yet been fixed upstream (please report those to the upstream project, but you may notify us so we can update).

**Security practices worth knowing**
Network access happens only when you ask for it: installing resources, syncing, contacting an AI provider you configured, approved web research, update checks, or optional error reporting. There is no telemetry.
API keys you add are stored in data/api-credentials.json with restrictive file permissions (0600 on Unix). Ordinary sync backups do not include them; an encrypted export is required to carry AI settings and keys.
Standard .gbz sync backups are unencrypted — treat the file like a password and store it somewhere you trust.
The AI assistant is disabled by default and bundles no model; cloud use requires your own key, and web research asks for permission first.
Restore is additive: differing records keep the version already on the machine, and deletions are applied only if you explicitly opt in.
Error logs contain only the app's own faults, with paths normalised and no personal data; reporting an error always requires you to press the button.
Thanks for helping keep G-Bible and its users safe.
