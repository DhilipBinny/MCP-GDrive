# Assumptions — Google Workspace MCP

Explicit record of what we assumed during design. Review when bugs surface — the root cause is often an invalidated assumption.

## Status Key
- **Open** — assumed but not yet validated
- **Validated** — confirmed correct by testing or stakeholder
- **Invalidated** — proven wrong, linked to the fix

---

## Authentication

| # | Assumption | Impact if Wrong | Status |
|---|-----------|----------------|--------|
| 1 | OAuth tokens refresh automatically via refresh_token | If Google revokes refresh token (testing mode, 7-day expiry), user must re-auth manually | Validated |
| 2 | OS keyring is available on most desktop systems | Headless Linux/Docker falls back to plaintext file — acceptable for dev but not production secrets | Validated |
| 3 | One credential set covers all four API scopes (Docs, Sheets, Slides, Drive) | If scope mismatch, specific API calls fail with 403 | Validated |
| 4 | Service account mode doesn't need interactive browser auth | Correct, but domain-wide delegation must be configured in Google Admin | Validated |
| 5 | GCP apps in "testing" mode expire tokens after 7 days | Users must either publish the app or re-auth weekly | Open |

## Google API Behavior

| # | Assumption | Impact if Wrong | Status |
|---|-----------|----------------|--------|
| 6 | Google Docs uses UTF-16 code units for text indices | If wrong, all insert/delete operations break with index errors | Validated |
| 7 | batchUpdate requests execute atomically (all-or-nothing) | If partial execution, document left in inconsistent state | Open |
| 8 | Google API rate limits are 300 requests/min for Docs/Sheets/Slides | If limits are lower per-project, need more aggressive backoff | Open |
| 9 | Drive API file listing returns all accessible files (not just owned) | If scoped to owned only, shared files won't appear in search | Validated |
| 10 | Exponential backoff with max 5 retries handles transient 429/5xx errors | If persistent outage, user gets error after ~2 min of retries | Validated |

## Data & Content

| # | Assumption | Impact if Wrong | Status |
|---|-----------|----------------|--------|
| 11 | Markdown is sufficient for document content creation | Complex formatting (columns, text boxes, embedded objects) not supported | Validated |
| 12 | Draw.io XML covers common diagram types | Unusual shapes or connectors may not convert correctly | Open |
| 13 | Text width estimation (char-class heuristic) is accurate within 15% | If underestimate, text overflows shapes in slides | Open |
| 14 | Google Sheets cell values are strings, numbers, or booleans | Formulas returned as computed values unless specifically requested | Validated |
| 15 | Sheet names with special characters need quoting in A1 notation | Missing quotes cause API errors on sheets named "Q2 Data" etc. | Validated |

## Deployment & Usage

| # | Assumption | Impact if Wrong | Status |
|---|-----------|----------------|--------|
| 16 | Servers run as single-process, single-user (one credential per instance) | Concurrent users would share or conflict on credentials | Open |
| 17 | stdio transport is the only needed transport (no HTTP/SSE) | If MCP clients need HTTP, must add transport option | Open |
| 18 | `uvx --from git+...` is a valid install method for end users | If uv changes git install behavior, install instructions break | Open |
| 19 | Python 3.11+ is available on target systems | 3.10 users can't install; 3.12+ may have compatibility issues | Validated |
| 20 | Keyring package backends vary by OS — secretstorage on Linux, macOS Keychain, Windows Credential Locker | If backend unavailable (Docker, WSL), file fallback activates | Validated |

---

*Last reviewed: 2026-10-16*
