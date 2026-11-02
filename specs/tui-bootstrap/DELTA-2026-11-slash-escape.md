# DELTA 2026-11 — `//` escape for messages starting with `/` (prismal-tui)

| Field | Value |
|---|---|
| **Author** | Ernesto Crespo |
| **Status** | `DONE` |
| **Version** | 1.0 |
| **Date** | 2026-11-02 |
| **Applies to** | `tui-bootstrap` (`SPEC`/`TASKS`) — ships in `0.1.1` |

## 1. Rationale

Since `0.1.0`, any input starting with `/` is a slash command, so a message
such as "/etc/hosts doesn't resolve" can't be sent at all. Doubling the slash
is the usual chat-client escape: `//text` sends `/text`.

## 2. MODIFIED requirements

| ID | Change | EARS acceptance criterion |
|---|---|---|
| SPEC-TUI-SES-004 | One narrow exception: the escape slash | THE SYSTEM SHALL pass user text to `send_message(content=…)` unmodified, EXCEPT that WHEN the input starts with `//` it SHALL remove exactly the first `/` (the escape the user typed). No other templating, prefixing or prompt construction is allowed. |
| SPEC-TUI-UX-001 | `/`-prefixed means *single* `/` | WHEN the input starts with a single `/` (not `//`), THE SYSTEM SHALL treat it as a slash command. An unknown command SHALL show the "unknown command" hint and SHALL NOT be sent. |

## 3. ADDED requirements

| ID | Requirement | Prio |
|---|---|---|
| SPEC-TUI-UX-006 | WHEN the user submits input starting with `//`, THE SYSTEM SHALL send it as a message with the first `/` removed (`//etc/hosts` → `/etc/hosts`, `///x` → `//x`), render that same text as the user line, and list the escape in `/help`. | `MUST` |

## 4. Tasks

| ID | Task | Est. | Dep | SPEC | Status |
|---|---|---|---|---|---|
| TUI-E-01 | `commands.escaped_message` + `is_command` excludes `//`; `Composer` sends the unescaped text; `/help` line; unit + Pilot tests | 0.2 d | — | SES-004, UX-001, UX-006 | `DONE` |
| TUI-E-02 | Docs (`configuration.md`, CLAUDE.md checklist), `0.1.1` CHANGELOG | 0.1 d | E-01 | — | `DONE` |

## Change History

| Version | Date | Author | Changes |
|---|---|---|---|
| 1.0 | 2026-11-02 | Ernesto Crespo | `//` escape for messages starting with `/` |
