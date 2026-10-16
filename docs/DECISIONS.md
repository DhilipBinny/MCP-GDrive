# Architecture Decision Records — Google Workspace MCP

Append-only log of significant technical decisions. Never delete an ADR — if reversed, add a new one that supersedes it.

---

## ADR-001: Action-Based Dispatch Over Individual Tools

**Date:** 2025-03-01
**Status:** Accepted

### Context
The initial design could expose each Google API operation as a separate MCP tool (115+ tools) or consolidate related operations under fewer tools with an `action` parameter. LLM context windows are finite, and each tool's schema consumes tokens.

### Decision
Use action-based dispatch — 26 consolidated tools instead of 115 individual ones. Each tool groups related operations (e.g., `gdocs_write` handles write_markdown, append_markdown, insert_at_section, replace, delete_section, etc.).

### Consequences
**Positive:**
- Dramatically less LLM context usage (26 tool schemas vs 115)
- Related operations grouped logically — easier for LLMs to discover capabilities
- Single error handling wrapper per tool group

**Negative:**
- Larger individual tool schemas with more parameters
- Action routing logic inside each tool function
- Some parameters only apply to specific actions (must document clearly)

---

## ADR-002: OS Keyring for Token Storage

**Date:** 2025-03-01
**Status:** Accepted

### Context
OAuth tokens need persistent storage. Options: plaintext file, encrypted file, OS keyring, environment variable.

### Decision
Store OAuth tokens in the OS keyring (macOS Keychain, Windows Credential Locker, Linux libsecret) as the primary storage, with JSON file fallback at the platform-correct config path when keyring is unavailable (headless Linux, Docker).

### Consequences
**Positive:**
- Tokens encrypted at rest by the OS
- No plaintext credentials in the filesystem by default
- Cross-platform without user configuration

**Negative:**
- Keyring availability varies (headless Linux, Docker, CI)
- Requires `keyring` package dependency
- File fallback means tokens may be plaintext on some systems

---

## ADR-003: Shared Auth Module Across Servers

**Date:** 2025-03-01
**Status:** Accepted

### Context
Three separate MCP servers (Docs, Sheets, Slides) all need Google API authentication. Each could manage its own credentials, or they could share.

### Decision
Single `shared/auth.py` module used by all three servers. One OAuth flow authenticates for all scopes (Docs, Sheets, Slides, Drive). Credential caching is global per process.

### Consequences
**Positive:**
- One-time auth covers all servers
- Consistent credential handling and error messages
- Token refresh logic in one place

**Negative:**
- Broad scope request (all four APIs) even if user only needs one
- Can't run servers with different credentials simultaneously

---

## ADR-004: Draw.io XML for Diagram Creation

**Date:** 2025-03-01
**Status:** Accepted

### Context
Google Slides has no native diagram API. Options: manually position shapes via the API, use an intermediate format, or skip diagram support.

### Decision
Accept draw.io XML as input, parse it, and convert to Google Slides API shape/connector requests. Includes auto-scaling text fitting and connector routing.

### Consequences
**Positive:**
- Rich diagram support (flowcharts, architecture diagrams, ERDs)
- LLMs are familiar with draw.io XML format
- Auto-scaling prevents text overflow

**Negative:**
- Complex conversion logic (`drawio_converter.py`)
- Not all draw.io features map to Slides shapes
- Curated shape index (58 shapes) limits available shapes

---

## ADR-005: FastMCP Framework

**Date:** 2025-03-01
**Status:** Accepted

### Context
Need an MCP server framework for Python. Options: raw MCP protocol handling, FastMCP, custom wrapper.

### Decision
Use FastMCP from the `mcp` package — it provides decorator-based tool registration, stdio transport, and handles the MCP protocol lifecycle.

### Consequences
**Positive:**
- Minimal boilerplate for tool registration
- Built-in stdio transport (Claude Code compatible)
- Type-safe parameter definitions from function signatures

**Negative:**
- Tied to the `mcp` package release cycle
- Less control over protocol-level behavior

---

## ADR-006: Service Credential Freshness Tracking

**Date:** 2025-07-15
**Status:** Accepted

### Context
Google API service objects cache credentials. When an OAuth token refreshes, the cached service still uses the old token, causing auth failures.

### Decision
Each service module tracks `_service_creds` alongside `_service`. On every call, compare current credentials to cached — rebuild the service if they differ.

### Consequences
**Positive:**
- Transparent credential refresh — no user-facing errors
- No need for manual service reconstruction

**Negative:**
- Global mutable state per service module
- Identity comparison (`is not`) relies on credential object lifecycle
