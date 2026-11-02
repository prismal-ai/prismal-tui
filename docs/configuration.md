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
`/delete [name]`, `/cancel`, `/quit`, `/help`. Any input that starts with `/`
is treated as a command and is never sent to the engine.

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

# throwaway store + verbose log
PRISMAL_TUI_STORE_PATH=/tmp/prismal-tui/conversations.db \
PRISMAL_TUI_LOG_LEVEL=DEBUG \
prismal-tui
```
