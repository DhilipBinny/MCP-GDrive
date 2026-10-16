# Code Review Standards

This file customizes `/code-review` behavior. Every review agent receives these instructions.

## Review Dimensions (All Required)

1. **Correctness** — Logic bugs, off-by-one errors, None access, race conditions, unhandled error paths, UTF-16 index math errors
2. **Security** — Hardcoded secrets, path traversal, eval/exec, missing input validation, stack trace exposure, credential leaks
3. **Modularity** — Functions over 50 lines, duplicate code, monolithic files, violation of existing patterns (action dispatch, service layer separation)
4. **Constants** — Magic strings/numbers in business logic, hardcoded config values
5. **Testing** — New feature/fix without tests, missing edge case coverage
6. **Debug Artifacts** — print() debug statements, commented-out code, bare TODOs without ticket refs
7. **Dependencies** — Unnecessary new packages, stdlib alternatives available, unaudited deps
8. **Error Handling** — Missing boundary handling, user-facing stack traces, no retry for transient Google API failures
9. **Performance** — O(n^2) where O(n) works, N+1 API calls, unbounded result sets without pagination
10. **Type Safety** — Missing type hints, overly broad types, untyped function signatures

## Severity Levels

- **critical** — Will break in production, security vulnerability, data loss risk
- **warning** — Works but fragile, performance issue, missing test coverage
- **nit** — Style, naming, minor improvement, non-blocking

## Review Style

- Be specific: cite exact line numbers and symbol names
- Give concrete fixes, not vague suggestions
- Skip explaining what the code does — the reviewer can see the diff
- Group related findings, don't repeat the same issue on every occurrence
- If nothing to flag: "LGTM"

## Project-Specific Checks

- Google API calls use `execute_with_retry()` from `shared/utils.py`
- Service modules track `_service_creds` for credential freshness
- New tools wrapped with `@_handle_errors` decorator
- Action dispatch follows existing `Literal[...]` routing pattern
- Tool docstrings match actual parameter names and accepted values

## BANNED in commit messages (escalate to critical)

- "Co-Authored-By" lines
- AI attribution (Claude, Anthropic, etc.)
- Iteration/audit references ("2nd pass", "found in review")
- Vague messages ("fix bugs", "updates", "WIP")
