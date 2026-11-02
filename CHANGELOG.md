# Changelog

All notable changes to `prismal-tui`. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.1.0] — 2026-11-02

First release. A Textual terminal front-end for `prismal-server`, built only
on `prismal-sdk` (`>=0.2,<1`). It installs from source: `prismal-sdk` 0.2 is
not on PyPI yet, so check out `../prismal-sdk` next to this repo. PyPI is
`TUI-FUTURE-01`.

### Added

- **Chat.** Streamed answers rendered with frame-based coalescing and
  re-rendered as Markdown when the turn ends. Tool calls show as `⚙` lines.
  User text reaches the engine unmodified.
- **Conversations.** A sidebar plus `/new`, `/switch`, `/rename` and
  `/delete` for named local conversations. Each maps to one durable engine
  thread in a local SQLite store, which holds no messages and no secrets.
  The mapping is persisted before the first message is sent.
- **Cancel.** `Esc` (or `PRISMAL_TUI_CANCEL_KEY`) and `/cancel` close the
  stream, and the host cancels the run. Partial text is always kept.
- **Errors.** Friendly copy in the transcript, the status bar and a toast.
  No error codes, server messages or tracebacks are shown, and nothing is
  retried automatically.
- **Usage (DELTA-2026-10).** A status-bar readout of the last turn and the
  session (tokens, cache %, cost labels `~`, `(plan)`, `$?` and `*`).
  `/usage` and `/usage all` open a modal fed by the server's
  `GET /v1/usage`. A budget stop reads "Budget limit reached on the server —
  run /usage for details".
- **Polish.** Status bar with connection state and key hints, help on `F1`
  and `/help`, and a background health check that never blocks startup.
- **Configuration.** `PRISMAL_TUI_*` environment variables only, validated
  at startup without echoing values (see `docs/configuration.md`). The token
  is a `SecretStr` that never reaches the screen, the store or the log. The
  log file is mode `0600` and holds no message text.
- **Quality.** Offline unit and Pilot UI suites with a coverage floor of
  97%, an AST boundary guard, an end-to-end secret-leak test and a
  responsiveness probe. An opt-in `contract` suite runs against a live
  `prismal-server` 0.2, which CI can start in fake-LLM mode.

[0.1.0]: https://github.com/prismal-ai/prismal-tui/releases/tag/v0.1.0
