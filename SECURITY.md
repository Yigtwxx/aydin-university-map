# Security policy

## Supported versions

Only the `main` branch is supported.

## Reporting a vulnerability

Please **do not open a public issue**. Report it privately through GitHub:
**Security → Report a vulnerability**
(<https://github.com/Yigtwxx/aydin-university-map/security/advisories/new>).

Include what is affected (pipeline, API, web app), steps to reproduce and the
impact. You can expect an initial reply within 7 days.

## Scope notes

- Leaked credentials (API keys, database URLs) and exposure of the copyrighted
  tour data are treated as security issues.
- The offline pipeline runs on a maintainer machine; its local data sink binds to
  `127.0.0.1` only and requires a per-session token.
