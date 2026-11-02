# Manual verification checklist (TUI-03-05)

Run before each release against a real `prismal-server`. Offline coverage for
every item already exists in `tests/` (fake SDK client + Textual `Pilot`);
this checklist proves the same behaviour end-to-end through the real SDK and
host.

## Setup

```bash
# terminal 1 — host in deterministic fake-LLM mode (no provider, no credential)
cd ../prismal-server
PRISMAL_SERVER_HOST_FAKE_LLM_MODE=true uvicorn prismal_server.app:app --port 8765

# terminal 2 — the TUI, with a throwaway store
cd ../prismal-tui
PRISMAL_TUI_SERVER_URL=http://127.0.0.1:8765 \
PRISMAL_TUI_STORE_PATH=/tmp/prismal-tui-check/conversations.db \
uv run prismal-tui
```

The fake host answers `echo: <content>` in ≤16-char token chunks, a
`fake_tool` call for `/tool <q>`, and a terminal `internal_error` for
`/error` (see `prismal-server/docs/fake-mode.md`).

## Checklist

| # | Scenario | Steps | Expected | 2026-11-02 (host 0.2 fake mode, SDK 0.2.0.dev0) |
|---|---|---|---|---|
| 1 | Startup / health | Launch with the host running | Status bar `● connected 127.0.0.1:8765` | ✅ live |
| 2 | Normal turn | Type `hello **world**`, Enter | Reply streams, then renders as Markdown | ✅ live |
| 3 | Tool-call activity | Send content `/tool weather` ¹ | Dimmed `⚙ using fake_tool…` line in stream order | ✅ live ¹ |
| 4 | Server error | Send content `/error` ¹ | "Something went wrong on the server — try again." in transcript, status bar and toast; no `internal_error` / `fake error` anywhere | ✅ live ¹ |
| 5 | Cancel mid-turn | Send a long message, press `Esc` while streaming | Stream stops, partial text kept, `— cancelled —` note | ⚠️ not reproducible live: the fake host streams a full reply faster than a keypress lands. Covered offline (`test_escape_cancels_and_keeps_partial_text`, session cancel tests). Re-check against a real LLM-backed host. |
| 6 | Conversations | `/new second`, send, `/switch default`, `/rename`, `/delete` | Each conversation has its own thread; sidebar ordered by activity | ✅ live (`/new`, send, `/switch`) |
| 7 | Quit | `/quit` or `ctrl+q` | Exits cleanly, no traceback | ✅ live |
| 8 | Restart continuity | Quit, relaunch with the same store, `/switch default`, send | "Continuing 'default'…" note; reply arrives on the same `thread_id` | ✅ live |
| 9 | Server down | Stop the host, send a message | `○ disconnected`, "Can't reach prismal-server — check PRISMAL_TUI_SERVER_URL…"; app keeps running | ✅ live |
| 10 | Budget exceeded | Host with a tenant budget that is already exhausted | "Budget limit reached on the server — run /usage for details" (DELTA-2026-10, TUI-D-07); partial text kept | ⏳ needs a budget-configured host (not available in fake mode). Covered offline (`test_error_paths.py::budget`). |
| 11 | Policy denied | Host with a policy that denies the prompt | "That request can't be processed."; no rule name / code shown | ⏳ needs a policy-configured host. Covered offline (`test_error_paths.py::policy`). |
| 12 | Store hygiene | Inspect the store file after a session | Only the `conversations` table (ids, names, thread ids, timestamps) — no message text, no token | ✅ live |

¹ The composer treats any input starting with `/` as a slash command, so the
fake host's `/tool` and `/error` triggers cannot be typed into the TUI. The
2026-11-02 run drove the same turn path (`PrismalTuiApp.run_turn`)
programmatically with that content. With a real LLM-backed host, use a
prompt that triggers a tool and a host misconfiguration instead.
