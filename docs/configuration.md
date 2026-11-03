# Configuration reference

`prismal-tui` is configured **only** through `PRISMAL_TUI_*` environment
variables (no config file in v0.1 — that is `TUI-FUTURE-02`). Settings are
validated at startup, before the terminal UI is drawn; an invalid value
exits with status `2` and a message naming the variable and the rule it
broke. The message never repeats the value you set, so a token pasted into
the wrong variable is never echoed back.

## Variables

| Variable | Default | Meaning | Validation |
|---|---|---|---|
| `PRISMAL_TUI_SERVER_URL` | `http://localhost:8000` | The `prismal-server` to talk to | Absolute `http://` or `https://` URL with a host |
| `PRISMAL_TUI_TOKEN` | *(unset)* | Bearer credential for the server | Kept as a secret (see below) |
| `PRISMAL_TUI_ORG_ID` | *(unset)* | Tenant applied to every request (`X-Org-Id`, set by the SDK) | Empty string = unset |
| `PRISMAL_TUI_STORE_PATH` | *user data dir*`/conversations.db` | SQLite file mapping local conversation names to engine threads | Parent directory is created on first run; a permission error is a startup error |
| `PRISMAL_TUI_CANCEL_KEY` | `escape` | Key that cancels the answer in progress | A Textual key name, optionally with modifiers (`ctrl+x`, `f2`, `ctrl+shift+c`). A bare printable character (`a`) is rejected — it would be swallowed while typing |
| `PRISMAL_TUI_LOG_LEVEL` | `INFO` | Verbosity of the local log file | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `PRISMAL_TUI_SHOW_USAGE` | `true` | Show the token/cost readout in the status bar (`/usage` works either way) | Boolean (`true`/`false`, `1`/`0`) |
| `PRISMAL_TUI_PROTOCOL` | `prismal` | Turn stream: `prismal` (native SSE) or `ag-ui` (needed to see and answer agent questions with `/resume`; see below) | `prismal` or `ag-ui` |

The *user data dir* comes from [`platformdirs`](https://pypi.org/project/platformdirs/):

| OS | Default directory |
|---|---|
| Linux | `~/.local/share/prismal-tui/` (or `$XDG_DATA_HOME/prismal-tui/`) |
| macOS | `~/Library/Application Support/prismal-tui/` |
| Windows | `%LOCALAPPDATA%\prismal-tui\` |

## Files the TUI writes

Both files live in the store's directory.

- **`conversations.db`** (SQLite, WAL mode, plus `-wal`/`-shm` side files):
  one row per local conversation, with `id`, `name`, `thread_id`,
  `created_at` and `last_active_at`. It holds **no message content** (the
  engine keeps history under the `thread_id`) and **no credentials**.
  Deleting a conversation (`/delete`) removes only this row; the server
  keeps the history.
- **`prismal-tui.log`** (mode `0600`): turn start and finish, conversation
  and thread ids, event counts, and mapped error types and codes. It never
  contains message text, exception messages (they can carry content) or
  secrets. Nothing is logged to the terminal the app draws on.

## Secrets

`PRISMAL_TUI_TOKEN` is read once into a `SecretStr` and handed only to the
`prismal-sdk` client constructor. It never appears on screen, in the store,
in the log or in an error message. `tests/ui/test_secret_leak.py` enforces
this end to end, against a hostile server that echoes the token back.

The status bar shows only the server's `host:port`, so credentials embedded
in `PRISMAL_TUI_SERVER_URL` (`https://user:pass@host`) are never displayed.
Prefer `PRISMAL_TUI_TOKEN` over URL credentials anyway.

## Usage and cost

`prismal-server` ≥ 0.2 attaches a `Usage` object to every finished turn and
serves `GET /v1/usage`. The TUI only **displays** these values: it never
computes, re-prices or stores them. The server is the source of truth.

**Status bar** (after each turn, unless `PRISMAL_TUI_SHOW_USAGE=false`):

```
last: <prompt>/<completion> tok · cache <p>% · <cost>  session: <total> tok · <cost>
```

- `session` is the in-memory sum for this conversation since the app started.
  It resets on restart and is never written to `conversations.db`.
- `cache <p>%` is `Usage.cache_hit_ratio` (`cache_read_tokens / prompt_tokens`).
  It shows `—` when there were no prompt tokens.
- Cost labels:

  | Label | Meaning |
  |---|---|
  | `$0.0043` | priced exactly (`estimated = false`) |
  | `~$0.0043` | estimated (`estimated = true`) |
  | `~$0.0043 (plan)` | `cost_source = subscription` (a flat-rate plan) |
  | `$?` | `cost_source = none` (no price available) |
  | `…*` | the total mixes several cost sources |

- `(n/a)`: the last turn reported no usage (a 0.1 server, or the engine sent
  none). The previous readout stays.

**`/usage`** asks the server for this conversation's thread, since the
conversation was created locally. **`/usage all`** asks for the whole
tenant, since today 00:00 local time. A 0.1 server answers `404`, and the TUI
then says *"usage reporting requires prismal-server ≥ 0.2"*.

The fields shown come from the `prismal-sdk` models (`SPEC-CS2-USG-*`):

| Model | Fields the TUI shows |
|---|---|
| `Usage` (per turn, totals, per model) | `prompt_tokens` (includes cache reads and writes), `cache_read_tokens`, `cache_write_tokens`, `completion_tokens`, `reasoning_tokens`, `total_tokens`, `calls`, `cost_usd`, `cost_source`, `estimated`, `served_model`, `gateway`, `cache_hit_ratio` (property) |
| `UsageReport` (`/usage`) | `totals`, `cache_hit_ratio`, `by_model` (one row each: `served_model`, `gateway`, `cost_source`, `cost_usd`), `turns` (count only), `next_cursor` (shown as "+ more") |

When a turn hits a server-side budget (`budget_exceeded`: HTTP 402 before the
turn, or a terminal `error` event mid-stream), the transcript keeps any partial
answer and shows *"Budget limit reached on the server — run /usage for
details"*.

## Agent questions and `/resume` (AG-UI)

Some engine routes pause and ask a human first (approval gates, the
computer-use agent). `prismal-server` 0.3 only reports these pauses on
AG-UI streams, so the native stream ends such a turn with an empty answer.
To see and answer them, run with `PRISMAL_TUI_PROTOCOL=ag-ui` against a host
with AG-UI enabled (`PRISMAL_SERVER_HOST_AGUI_ENABLED=true` on the host and
`PRISMAL_AGUI_EVENTS_ENABLED=true` for the engine). Otherwise every turn
shows *"AG-UI isn't enabled on this server — …"*.

When the agent pauses, the transcript shows one line per open question, then
a hint:

```
⏸ Waiting for your answer — human_approval: Approve the deploy?
Answer with /resume <answer> (JSON or text)
```

`/resume <answer>` answers **every** open question with the same answer:

- valid JSON is sent as the decoded value — engine approval gates expect an
  object, e.g. `/resume {"action": "approve"}` or
  `/resume {"action": "reject"}`;
- anything else is sent as the exact text (surrounding spaces trimmed);
- `/resume` alone sends `null`.

The TUI never turns words into actions (`/resume approve` sends the string
`"approve"`, which an approval gate treats as a rejection), and never re-sends
an answer by itself. Re-sending one manually is safe: the server answers
*"Nothing is waiting for an answer any more — …"* instead of running it
twice.

Open questions live in memory only: they are not in the store and are lost
when the TUI restarts (the server has no way to list them). A plain message
sent while a question is open goes to the engine as usual.

## Keys and commands

| Key | Action |
|---|---|
| `PRISMAL_TUI_CANCEL_KEY` (default `Esc`) | Cancel the answer in progress (active only while answering) |
| `ctrl+n` | New conversation |
| `tab` | Move between the sidebar and the composer |
| `↑`/`↓`, `enter` | Pick a conversation in the sidebar |
| `F1` | Help |
| `ctrl+q` | Quit |

Slash commands: `/new [name]`, `/switch <name>`, `/rename <name>`,
`/delete [name]`, `/usage [all]`, `/resume [answer]`, `/cancel`, `/quit`, `/help`. Any input that starts with a single `/`
is treated as a command and is never sent to the engine. To send a message
that starts with `/`, double it: `//etc/hosts …` sends `/etc/hosts …`.

## Examples

```bash
# local dev server, defaults
prismal-tui

# remote, authenticated, scoped to a tenant, ctrl+x to cancel
PRISMAL_TUI_SERVER_URL=https://prismal.example.com \
PRISMAL_TUI_TOKEN="$(pass show prismal/token)" \
PRISMAL_TUI_ORG_ID=acme \
PRISMAL_TUI_CANCEL_KEY=ctrl+x \
prismal-tui

# answer approval gates (host with AG-UI enabled)
PRISMAL_TUI_PROTOCOL=ag-ui prismal-tui

# throwaway store + verbose log
PRISMAL_TUI_STORE_PATH=/tmp/prismal-tui/conversations.db \
PRISMAL_TUI_LOG_LEVEL=DEBUG \
prismal-tui
```
