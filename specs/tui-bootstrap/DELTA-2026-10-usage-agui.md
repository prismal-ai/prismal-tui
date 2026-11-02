# DELTA 2026-10 — usage & AG-UI (prismal-tui)

| Field | Value |
|---|---|
| **Author** | Ernesto Crespo |
| **Status** | `READY` |
| **Version** | 1.0 |
| **Date** | 2026-10-04 |
| **Applies to** | `tui-bootstrap` (`PLAN`/`ARCHITECTURE`/`SPEC`/`TASKS`) — folded into `0.1.0` |
| **Source** | `prismal/docs/gap-analysis-gateways-tokens-decisions-2026-10.md` §6 |

## 1. Rationale

The TUI's user is a developer or operator running their own sessions — the
person who most benefits from seeing whether prompt caching works and what a
turn costs. `prismal-server` 0.2 attaches `Usage` to every `done` event and
exposes `GET /v1/usage`. This delta adds a status-bar usage readout (last turn
and session) and a `/usage` command. AG-UI is **not** adopted: the classic SSE
stream already carries everything the transcript renders.

## 2. Dependencies

- `prismal-sdk` `>=0.2,<1` (`SPEC-CS2-*`): `Usage` (12 keys; `prompt_tokens` includes cache reads and
  writes; property `cache_hit_ratio`), `DoneEvent.usage: Usage | None`,
  `usage(*, thread_id=None, since=None, until=None, limit=100, cursor=None, org_id=None) -> UsageReport`
  (`totals`, `cache_hit_ratio`, `by_model: list[Usage]`, `turns: list[UsageTurn]`, `next_cursor`).
- `prismal-server` `0.2.0` (RH2); `/v1/usage` defaults `since` to now − 24 h; contract tests use
  `host_fake_llm_mode`.
- Resolved: `budget_exceeded` (HTTP 402 before the turn, terminal `error` event mid-stream) is defined in
  RH2 §11 and mapped to `BudgetExceededError` in CS2 §7 (`TUI-D-01` only pins the fixture).

## 3. MODIFIED requirements

| ID | Change | EARS acceptance criterion |
|---|---|---|
| SPEC-TUI-NFR-005 | SDK pin → `prismal-sdk>=0.2,<1` | THE SYSTEM SHALL declare `prismal-sdk>=0.2,<1`; a dependency test SHALL fail on a lower floor. |
| SPEC-TUI-SES-002 | Event translation also captures `DoneEvent.usage` | WHEN a `DoneEvent` arrives, THE SYSTEM SHALL pass its `usage` (possibly `None`) to the session's `UsageTally` before signalling turn completion. |
| SPEC-TUI-UX-004 | Slash-command set gains `/usage` | THE SYSTEM SHALL list `/usage` in `/help` and dispatch it like the other slash commands. |
| SPEC-TUI-ERR-002 | `budget_exceeded` copy refined | WHEN a turn fails with a `PrismalAPIError` whose `code == "budget_exceeded"`, THE SYSTEM SHALL show "Budget limit reached on the server — run /usage for details" and keep the partial transcript. |

## 4. ADDED requirements

| ID | Requirement | Prio |
|---|---|---|
| SPEC-TUI-USG-001 | THE SYSTEM SHALL keep a per-conversation, in-memory `UsageTally(last: Usage \| None, session_totals: Usage)` (field-wise sum of the numeric `Usage` keys) that resets when the process restarts and is never written to `ConversationStore`. | `MUST` |
| SPEC-TUI-USG-002 | WHEN a turn completes with non-`None` usage, THE SYSTEM SHALL update the status bar to `last: <prompt_tokens>/<completion_tokens> tok · cache <p>% · <cost>  session: <total_tokens> tok · <cost>` within one frame. | `MUST` |
| SPEC-TUI-USG-003 | THE SYSTEM SHALL display cache % from `Usage.cache_hit_ratio` (last turn) and from the same property on the session total, rendering `—` WHEN `prompt_tokens == 0`; it SHALL NOT use its own formula. | `MUST` |
| SPEC-TUI-USG-004 | THE SYSTEM SHALL render `cost_usd` as `$<x>`, prefixed `~` WHERE `estimated` is `True`; WHERE `cost_source == "subscription"`, as `~$<x> (plan)`; WHERE `cost_source == "none"`, as `$?`; WHERE the session mixes sources, the session cost SHALL carry a `*` with "mixed sources" in `/usage`. | `MUST` |
| SPEC-TUI-USG-005 | IF `DoneEvent.usage` is `None`, THEN THE SYSTEM SHALL leave the previous readout, mark it `(n/a)` for the last turn, and raise no error (fail-open). | `MUST` |
| SPEC-TUI-USG-006 | WHEN the user runs `/usage`, THE SYSTEM SHALL call `usage(thread_id=<active thread>, since=<conversation created_at from ConversationStore, else now − 90 d>)` and render a modal: `totals` (prompt, cache read, cache write, completion, reasoning, `total_tokens`, `calls`, `cost_usd`, `cost_source`), `cache_hit_ratio`, one row per `by_model` entry (`served_model`, `gateway`, `cost_source`, `cost_usd`), and the number of `turns` ("+ more" WHEN `next_cursor` is set). | `MUST` |
| SPEC-TUI-USG-007 | WHEN the user runs `/usage all`, THE SYSTEM SHALL call `usage(since=<today 00:00 local, as UTC>)` and render the org-level `totals`, `cache_hit_ratio` and `by_model` for today. | `SHOULD` |
| SPEC-TUI-USG-008 | IF `usage()` raises (incl. `PrismalAPIError` with `status_code == 404` from a 0.1 server, or `InvalidRequestError` for a bad window), THEN THE SYSTEM SHALL show the mapped friendly toast ("usage reporting requires prismal-server ≥ 0.2" for 404) and keep the app responsive. | `MUST` |
| SPEC-TUI-USG-009 | WHERE `PRISMAL_TUI_SHOW_USAGE` is `False`, THE SYSTEM SHALL hide the status-bar readout (default `True`); `/usage` remains available. | `SHOULD` |
| SPEC-TUI-USG-010 | WHILE a turn is streaming, THE SYSTEM SHALL NOT call `usage()` automatically (no polling). | `MUST` |

## 5. Tasks (appended to `TASKS.md`)

| ID | Task | Est. | Dep | SPEC | Status |
|---|---|---|---|---|---|
| TUI-D-01 | **Verify before build**: pin the `budget_exceeded` fixture from RH2 §11 / CS2 §7; document the CS2 `Usage`/`UsageReport` fields shown by the TUI in `docs/configuration.md` | 0.2 d | — | ERR-002, USG-006 | `TODO` |
| TUI-D-02 | Bump SDK pin; extend `FakeAsyncPrismalClient` with `DoneEvent.usage` + `usage()` scripts seeded from the RH2 example payloads (incl. 404, `InvalidRequestError`) | 0.3 d | D-01 | NFR-005 | `TODO` |
| TUI-D-03 | `session/usage_tally.py`: `UsageTally` (session `Usage` sum) + formatting helpers (cache % via `cache_hit_ratio`, `estimated`/`subscription`/`none`/mixed cost labels) | 0.4 d | D-02 | USG-001, -003, -004, -005 | `TODO` |
| TUI-D-04 | `ConversationSession` passes `DoneEvent.usage` to the tally | 0.2 d | D-03 | SES-002 | `TODO` |
| TUI-D-05 | `widgets/statusbar.py` usage segment + `PRISMAL_TUI_SHOW_USAGE` setting | 0.4 d | D-03 | USG-002, -009 | `TODO` |
| TUI-D-06 | `/usage` and `/usage all` commands + `widgets/usage_modal.py` | 0.6 d | D-02 | UX-004, USG-006, -007 | `TODO` |
| TUI-D-07 | Error paths: 404/connection toasts, `budget_exceeded` copy | 0.3 d | D-06 | USG-008, ERR-002 | `TODO` |
| TUI-D-08 | Pilot UI tests: readout after turn, `n/a` case, `/usage` modal, no polling during stream | 0.5 d | D-05..07 | USG-002, -005, -006, -010 | `TODO` |
| TUI-D-09 | Contract test vs `prismal-server` 0.2 `host_fake_llm_mode`: turn → readout shows RH2 FAK-002 usage (15 tok, `$?`) → `/usage` `totals` include it | 0.3 d | D-08 | USG-006 | `TODO` |

Delta estimate: **~3.2 person-days**.

## 6. Test notes

- `UsageTally` property tests: session totals equal the sum of per-turn
  usages; `None` turns do not change totals.
- Formatting golden tests: `estimated`, `subscription`, `none`, `mixed`, zero-prompt, large numbers
  (thousands separators), reasoning-only output.
- Persistence test: after a turn with usage, the SQLite store file contains no
  `cost_usd`/token fields.
- Responsiveness test (extends `TUI-04-03`): `/usage` against a slow fake
  does not block composer input.

## 7. Out of scope

- AG-UI stream mode (classic SSE suffices for the transcript).
- Persisting usage history locally (the server is the source of truth).
- Budget/quota dashboards (`prismal-dashboard` DSH2).
- Client-side cost computation or price tables.

## Change History

| Version | Date | Author | Changes |
|---|---|---|---|
| 1.0 | 2026-10-04 | Ernesto Crespo | Delta: status-bar usage readout and `/usage` command |
