# DELTA 2026-11 — SDK 0.3 on PyPI, host 0.3 and interrupt resume (prismal-tui)

| Field | Value |
|---|---|
| **Author** | Ernesto Crespo |
| **Status** | `DONE` |
| **Version** | 1.0 |
| **Date** | 2026-11-03 |
| **Applies to** | `tui-bootstrap` (`SPEC`/`TASKS`). Ships in `0.2.0` |
| **Upstream** | `prismal-sdk` 0.3.0 (`specs/client-v0.3-agui-resume/`, PyPI `prismal-ai-sdk`) · `prismal-server` 0.3.0 (`specs/host-v0.3-agui-resume/`) · `prismal-ai` 3.22.1 |

## 1. Rationale

Three upstream releases landed on 2026-11-02:

| Upstream change | Impact on this repo |
|---|---|
| SDK published to PyPI as **`prismal-ai-sdk`** 0.3.0 (import module still `prismal_sdk`). The sibling checkout's project name changed too | **Breaking for us.** `uv sync` fails: the `prismal-sdk` path source now resolves to a project named `prismal-ai-sdk`. CI and the release workflow check out `../prismal-sdk`, which is no longer needed |
| SDK `run_agui(thread_id, content \| resume=…)`, `RunFinished.interrupts`, `AgUiInterrupt.resolve()`, `ResumeConflictError` | New capability: answer an engine approval gate from the terminal (Phase I) |
| Host 0.3 AG-UI interrupt resume on `POST /v1/agui`. Interrupts are **only** visible on AG-UI streams; the native SSE stream drops them | A TUI turn that hits an engine HITL gate today ends with an empty answer, and the user cannot answer the gate. Fixing that needs AG-UI turns (opt-in, because hosts ship AG-UI disabled by default) |
| Host 0.3 publishes `prismal-server` on PyPI; fake mode gains `/interrupt <message>` | The contract job installs the host wheel instead of checking out the repo, and can cover the resume round trip |
| Host 0.3 OTel traces, `decision_ollama_timeout_ms_by_tier`, engine graph close (H-320/H-322/H-3221) | None (host/operator side) |

## 2. MODIFIED requirements

| ID | Change | EARS acceptance criterion |
|---|---|---|
| SPEC-TUI-NFR-005 | SDK pin → `prismal-ai-sdk>=0.3,<1`, from PyPI | THE SYSTEM SHALL declare `prismal-ai-sdk>=0.3,<1` and SHALL NOT resolve it from a sibling checkout; a dependency test SHALL fail on a lower floor, on the old `prismal-sdk` name, or on a `[tool.uv.sources]` entry for the SDK. |
| SPEC-TUI-SES-002 | AG-UI turns are translated to the same UI events | WHERE `PRISMAL_TUI_PROTOCOL` is `ag-ui`, THE SYSTEM SHALL translate `TextMessageContent` (and `TextMessageChunk` with a text `delta`) to token events, `ToolCallStart` to tool activity, keep the `prismal.usage` value as the turn's usage, and end the turn on `RunFinished`. Other AG-UI events SHALL be ignored. |
| SPEC-TUI-SES-004 | A resume answer also passes through unmodified | WHEN the user runs `/resume <answer>`, THE SYSTEM SHALL send the answer as the resume payload: the decoded value WHEN `<answer>` is valid JSON, otherwise the exact string (surrounding whitespace trimmed, as for every command argument); `null` WHEN no answer is given. It SHALL NOT map answers to approve/reject or build payloads of its own. |
| SPEC-TUI-UX-004 | Slash-command set gains `/resume` | THE SYSTEM SHALL list `/resume [answer]` in `/help` and dispatch it like the other slash commands. |
| SPEC-TUI-CI-001 (was TUI-00-06) | Contract job uses the published host | THE CI contract job SHALL install `prismal-server>=0.3,<0.4` from PyPI into its own virtualenv, start it in fake-LLM mode with AG-UI enabled, and assert the fake-mode header before running the suite. |

## 3. ADDED requirements

| ID | Requirement | Prio |
|---|---|---|
| SPEC-TUI-AGU-001 | THE SYSTEM SHALL read `PRISMAL_TUI_PROTOCOL` (`prismal` \| `ag-ui`, default `prismal`). WHERE it is `prismal`, turns SHALL use `send_message(thread_id, text)` exactly as in 0.1. WHERE it is `ag-ui`, turns SHALL use `run_agui(thread_id, text)`. Any other value SHALL fail at startup naming the env var. | `MUST` |
| SPEC-TUI-AGU-002 | IF the host refuses AG-UI (`ProtocolNotEnabledError`), THEN THE SYSTEM SHALL show "AG-UI isn't enabled on this server — unset PRISMAL_TUI_PROTOCOL or enable AG-UI on the host." and keep the app responsive. | `MUST` |
| SPEC-TUI-INT-001 | WHEN an AG-UI run ends with `RunFinished.is_interrupted`, THE SYSTEM SHALL keep the partial answer, record the run's usage, and add one transcript note per interrupt: "⏸ Waiting for your answer — `<reason>`: `<message>`", followed by one hint "Answer with /resume <answer> (JSON or text)". | `MUST` |
| SPEC-TUI-INT-002 | THE SYSTEM SHALL keep a conversation's open interrupts in memory only (never in `ConversationStore`, never logged with content). Every finished run (`RunFinished`, from a message or a resume) SHALL replace them with that run's `interrupts` (`[]` on success). A `ResumeConflictError` SHALL clear them. A cancel or any other error SHALL leave them unchanged. | `MUST` |
| SPEC-TUI-INT-003 | WHEN the user runs `/resume [answer]` on a conversation with open interrupts and no turn in flight, THE SYSTEM SHALL call `run_agui(thread_id, resume=[i.resolve(payload) for i in open_interrupts])` (ids verbatim, every open interrupt answered, in host order), show the answer as the user line, and render the resumed run like any turn (tokens, tools, usage, cancel key, partial text kept). | `MUST` |
| SPEC-TUI-INT-004 | IF `/resume` runs while no interrupt is open, THEN THE SYSTEM SHALL show "Nothing is waiting for an answer in this conversation." and make no network call. | `MUST` |
| SPEC-TUI-INT-005 | THE SYSTEM SHALL never re-send a resume automatically (`SPEC-TUI-ERR-004`). It SHALL map `ResumeConflictError` `no_pending_interrupt` to "Nothing is waiting for an answer any more — it was already answered or the conversation moved on.", `resume_in_progress` to "That answer is still being processed — try again in a moment.", and a `ValidationError` with code `invalid_resume` or `unsupported_resume` to "The server didn't accept that answer." | `MUST` |
| SPEC-TUI-REL-001 | (Activates TUI-FUTURE-01.) WHEN a final version that is not yet on PyPI reaches `main`, THE release workflow SHALL run the gates (ruff, mypy, offline tests with the coverage floor), build, smoke-test the wheel and sdist, publish `prismal-tui` through PyPI trusted publishing (OIDC, environment `pypi`, no stored token), and only then tag `v<version>` and create the GitHub release. It SHALL do nothing for a `.devN` version or one already on PyPI. | `MUST` |
| SPEC-TUI-INT-006 | Open interrupts are lost on restart: the host has no route to list them. THE SYSTEM SHALL document this. A plain message sent while interrupts are open SHALL be sent as usual (what it does to the paused run is the engine's decision). | `MUST` |

## 4. Tasks

### Phase S — SDK 0.3 / host 0.3 alignment (no behaviour change)

| ID | Task | Est. | Dep | SPEC | Status |
|---|---|---|---|---|---|
| TUI-S-01 | Dependency → `prismal-ai-sdk>=0.3,<1` from PyPI, drop the path source, re-lock; dependency tests | 0.2 d | — | NFR-005 | `DONE` |
| TUI-S-02 | CI/release: no SDK checkout; contract job runs `prismal-server` 0.3 from PyPI (fake-LLM, AG-UI on); smoke test checks `prismal-ai-sdk>=0.3`; release tests | 0.3 d | S-01 | CI-001 | `DONE` |
| TUI-S-03 | `errors.py`: `ProtocolNotEnabledError`, `ResumeConflictError` (by code), resume `ValidationError` codes | 0.2 d | S-01 | AGU-002, INT-005 | `DONE` |
| TUI-S-04 | Docs: README, CLAUDE.md, `configuration.md`, CHANGELOG | 0.2 d | S-01..03 | — | `DONE` |

### Phase I — opt-in AG-UI turns and interrupt resume

| ID | Task | Est. | Dep | SPEC | Status |
|---|---|---|---|---|---|
| TUI-I-01 | `PRISMAL_TUI_PROTOCOL` setting + validation | 0.1 d | — | AGU-001 | `DONE` |
| TUI-I-02 | `FakeAsyncPrismalClient.run_agui` (scripted AG-UI turns, recorded resume entries) | 0.2 d | S-01 | NFR-001 | `DONE` |
| TUI-I-03 | `ConversationSession`: AG-UI turn translation, `TurnInterrupted` event, in-memory open interrupts, `resume()` | 0.6 d | I-01, I-02 | SES-002, INT-001..003, INT-005 | `DONE` |
| TUI-I-04 | `commands.py` `/resume` + `resume_payload()`; app dispatch, interrupt notes, `/help` line | 0.4 d | I-03 | UX-004, SES-004, INT-001, INT-003, INT-004 | `DONE` |
| TUI-I-05 | Pilot UI tests: interrupt notes, `/resume` round trip, nothing pending, conflict copy, default protocol unchanged | 0.4 d | I-04 | INT-001..005 | `DONE` |
| TUI-I-06 | Contract tests vs host 0.3 fake mode (`/interrupt` → `/resume` → `resumed:`; retry → conflict) | 0.3 d | I-05, S-02 | INT-003, INT-005 | `DONE` |
| TUI-I-07 | Docs + `0.2.0` CHANGELOG and version | 0.1 d | I-06 | INT-006 | `DONE` |

### Phase P — PyPI publication (activates TUI-FUTURE-01)

| ID | Task | Est. | Dep | SPEC | Status |
|---|---|---|---|---|---|
| TUI-P-01 | `release.yml` from `main` with trusted publishing; trimmed sdist; project URLs; release tests | 0.3 d | S-02 | REL-001 | `DONE` |
| TUI-P-02 | README install section, CLAUDE.md, CHANGELOG | 0.1 d | P-01 | REL-001 | `DONE` |

Delta estimate: **~3.5 person-days**.

## 5. Out of scope

- Approve/reject shortcuts (`/approve`): the payload shape is the engine's
  (`{"action": …}` today for HITL gates), and mapping words to payloads would
  put engine policy in the face. Revisit if the engine publishes a stable
  approval payload contract.
- `cancelled` resume entries (the host 0.3 refuses them).
- Showing interrupt `metadata` (may be large; the `message` is the
  human-facing question).
- Frontend tools (`RunAgentInput.tools`): the engine does not support them yet.
- AG-UI by default: hosts ship AG-UI disabled, so the default stays `prismal`.

## Change History

| Version | Date | Author | Changes |
|---|---|---|---|
| 1.0 | 2026-11-03 | Ernesto Crespo | SDK 0.3 on PyPI, host 0.3 contract job, opt-in AG-UI turns and `/resume` |
| 1.1 | 2026-11-03 | Ernesto Crespo | Phase P: PyPI publication (SPEC-TUI-REL-001, was TUI-FUTURE-01) |
