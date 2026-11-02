"""``PrismalTuiApp`` — the Textual application (SPEC-TUI-APP-001/004).

Wires settings, the SDK client, the ``ConversationStore`` and one
``ConversationSession`` per conversation to the widgets. This module is the
**only** place SDK exceptions raised by a turn are caught and mapped to
friendly text (SPEC-TUI-ERR-001/002); a failing turn never crashes the app or
touches other conversations (SPEC-TUI-ERR-005), and nothing is retried
automatically (SPEC-TUI-ERR-004).
"""

from __future__ import annotations

import logging
from typing import Any, Protocol
from urllib.parse import urlsplit

from prismal_sdk import (
    DoneEvent,
    PrismalSDKError,
    PrismalTransportError,
    TokenEvent,
    ToolCallEvent,
)
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import ContentSwitcher, Footer

from prismal_tui.commands import COMMANDS, Command
from prismal_tui.errors import STILL_ANSWERING, friendly_text, log_detail
from prismal_tui.session import (
    ChatClient,
    Conversation,
    ConversationSessions,
    SessionCancelled,
    TurnInFlightError,
)
from prismal_tui.session.models import ConversationNameTaken
from prismal_tui.settings import PrismalTuiSettings
from prismal_tui.store.conversation_store import ConversationStore
from prismal_tui.widgets.composer import Composer
from prismal_tui.widgets.sidebar import ConversationList
from prismal_tui.widgets.statusbar import StatusBar
from prismal_tui.widgets.transcript import AssistantTurn, TranscriptView

log = logging.getLogger("prismal_tui.app")

DEFAULT_CONVERSATION = "default"
CANCELLED_NOTE = "— cancelled —"


class AppClient(ChatClient, Protocol):
    """What the app needs from ``AsyncPrismalClient`` (health + close)."""

    async def healthz(self) -> Any: ...

    async def aclose(self) -> None: ...


def display_server(url: str) -> str:
    """``host[:port]`` only — never userinfo, path or query."""
    parts = urlsplit(url)
    host = parts.hostname or "?"
    return f"{host}:{parts.port}" if parts.port else host


class PrismalTuiApp(App[None]):
    TITLE = "prismal-tui"
    CSS = """
    #main { height: 1fr; }
    #chat { width: 1fr; }
    #transcripts { height: 1fr; }
    """
    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", priority=True),
        Binding("ctrl+n", "new_conversation", "New"),
        Binding("f1", "help", "Help"),
    ]

    def __init__(
        self,
        *,
        settings: PrismalTuiSettings,
        client: AppClient,
        store: ConversationStore,
    ) -> None:
        super().__init__()
        self.settings = settings
        self.client = client
        self.store = store
        self.sessions = ConversationSessions(client, store)
        self.active_id: str | None = None
        # SPEC-TUI-UX-002: the cancel key is configurable and must win over the
        # focused Input's own bindings, hence priority=True. It is only active
        # while the active conversation has a turn in flight (check_action).
        self._bindings.bind(settings.cancel_key, "cancel_turn", "Cancel", priority=True)

    # ── layout ─────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        with Horizontal(id="main"):
            yield ConversationList()
            with Vertical(id="chat"):
                yield ContentSwitcher(id="transcripts")
                yield Composer()
        yield StatusBar(display_server(self.settings.server_url))
        yield Footer()

    @property
    def statusbar(self) -> StatusBar:
        return self.query_one(StatusBar)

    @property
    def sidebar(self) -> ConversationList:
        return self.query_one(ConversationList)

    @property
    def composer(self) -> Composer:
        return self.query_one(Composer)

    def transcript(self, conversation_id: str | None = None) -> TranscriptView:
        cid = conversation_id or self.active_id
        return self.query_one(f"#t-{cid}", TranscriptView)

    # ── lifecycle ──────────────────────────────────────────────────────────

    async def on_mount(self) -> None:
        conversations = await self.store.list()
        if not conversations:
            conversations = [await self.store.create(DEFAULT_CONVERSATION)]
        await self._activate(conversations[0], resumed=conversations[0].thread_id)
        self.composer.focus()
        self.check_health()

    async def on_unmount(self) -> None:
        # SPEC-TUI-UX-005: close the SDK client and the store before exiting.
        self.sessions.cancel_all()
        try:
            await self.client.aclose()
        finally:
            await self.store.close()

    @work(exclusive=True, group="health")
    async def check_health(self) -> None:
        """SPEC-TUI-APP-004: a failed check degrades, never blocks startup."""
        self.statusbar.set_connection("connecting")
        try:
            await self.client.healthz()
        except Exception as exc:  # noqa: BLE001 — any failure = disconnected
            log.warning("healthz failed: %s", log_detail(exc))
            self.statusbar.set_connection("disconnected")
            self.statusbar.set_message(friendly_text(exc))
        else:
            self.statusbar.set_connection("connected")

    # ── conversations ──────────────────────────────────────────────────────

    async def _ensure_transcript(self, conversation: Conversation) -> TranscriptView:
        switcher = self.query_one(ContentSwitcher)
        existing = switcher.query(f"#t-{conversation.id}")
        if existing:
            view = existing.first(TranscriptView)
            return view
        view = TranscriptView(id=f"t-{conversation.id}")
        await switcher.mount(view)
        return view

    async def _activate(
        self, conversation: Conversation, *, resumed: str | None = None
    ) -> None:
        view = await self._ensure_transcript(conversation)
        if resumed and not view.children:
            view.add_note(
                f"Continuing '{conversation.name}' — earlier messages are kept "
                "by the server."
            )
        self.active_id = conversation.id
        self.query_one(ContentSwitcher).current = view.id
        await self._refresh_sidebar()
        self.refresh_bindings()

    async def _refresh_sidebar(self) -> None:
        await self.sidebar.show(
            await self.store.list(), self.active_id, self.sessions.in_flight_ids()
        )

    def note(self, text: str) -> None:
        """Inline, friendly system line in the active transcript."""
        self.transcript().add_note(text)

    async def on_conversation_list_picked(self, event: ConversationList.Picked) -> None:
        conv = await self.store.get(event.conversation_id)
        if conv is not None and conv.id != self.active_id:
            await self._activate(conv, resumed=conv.thread_id)
        self.composer.focus()

    # ── messages ───────────────────────────────────────────────────────────

    def on_composer_hint(self, event: Composer.Hint) -> None:
        self.note(event.text)

    async def on_composer_message_submitted(
        self, event: Composer.MessageSubmitted
    ) -> None:
        assert self.active_id is not None
        session = self.sessions.get(self.active_id)
        if session.in_flight:  # SPEC-TUI-SES-003: reject, never queue
            self.note(STILL_ANSWERING)
            return
        view = self.transcript()
        view.add_user(event.text)
        turn = view.begin_turn()
        self.run_turn(self.active_id, event.text, turn)

    @work(group="turns")
    async def run_turn(
        self, conversation_id: str, text: str, turn: AssistantTurn
    ) -> None:
        session = self.sessions.get(conversation_id)
        note: str | None = None
        try:
            stream = session.stream(text)
            self.call_after_refresh(self._turn_state_changed)
            async for event in stream:
                if isinstance(event, TokenEvent):
                    turn.feed(event.delta)
                elif isinstance(event, ToolCallEvent):
                    turn.activity(event.name)
                elif isinstance(event, DoneEvent):
                    self.statusbar.set_connection("connected")
        except SessionCancelled:
            note = CANCELLED_NOTE
        except TurnInFlightError:
            note = STILL_ANSWERING
        except PrismalSDKError as exc:  # SPEC-TUI-ERR-001/002
            log.warning(
                "turn failed conversation=%s %s", conversation_id, log_detail(exc)
            )
            note = friendly_text(exc)
            self.statusbar.set_message(note)
            if isinstance(exc, PrismalTransportError):
                self.statusbar.set_connection("disconnected")
        except Exception as exc:  # SPEC-TUI-ERR-005: never crash the app
            log.exception("unexpected error in turn conversation=%s", conversation_id)
            note = friendly_text(exc)
            self.statusbar.set_message(note)
        finally:
            await turn.finalize(note=note)  # keeps partial text (ERR-003)
            self._turn_state_changed()

    def _turn_state_changed(self) -> None:
        self.refresh_bindings()
        self.run_worker(self._refresh_sidebar(), group="sidebar", exclusive=True)

    # ── actions & commands ─────────────────────────────────────────────────

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "cancel_turn":
            return (
                self.active_id is not None
                and self.sessions.get(self.active_id).in_flight
            )
        return True

    def action_cancel_turn(self) -> None:
        if self.active_id is not None:
            self.sessions.get(self.active_id).cancel()

    async def action_new_conversation(self) -> None:
        await self._cmd_new(None)

    def action_help(self) -> None:
        self._cmd_help()

    async def on_composer_command_issued(self, event: Composer.CommandIssued) -> None:
        await self.dispatch_command(event.command)

    async def dispatch_command(self, command: Command) -> None:
        match command.name:
            case "new":
                await self._cmd_new(command.arg)
            case "switch":
                await self._cmd_switch(command.arg or "")
            case "rename":
                await self._cmd_rename(command.arg or "")
            case "delete":
                await self._cmd_delete(command.arg)
            case "cancel":
                if self.active_id and self.sessions.get(self.active_id).cancel():
                    return
                self.note("Nothing to cancel.")
            case "quit":
                self.exit()
            case "help":
                self._cmd_help()

    async def _unique_name(self) -> str:
        taken = {c.name.lower() for c in await self.store.list()}
        n = len(taken) + 1
        while f"chat-{n}" in taken:
            n += 1
        return f"chat-{n}"

    async def _cmd_new(self, name: str | None) -> None:
        try:
            conv = await self.store.create(name or await self._unique_name())
        except ConversationNameTaken:
            self.note(f"A conversation named '{name}' already exists.")
            return
        await self._activate(conv)

    async def _cmd_switch(self, name: str) -> None:
        conv = await self.store.get_by_name(name)
        if conv is None:
            self.note(f"No conversation named '{name}'.")
            return
        await self._activate(conv, resumed=conv.thread_id)

    async def _cmd_rename(self, name: str) -> None:
        assert self.active_id is not None
        try:
            conv = await self.store.rename(self.active_id, name)
        except ConversationNameTaken:
            self.note(f"A conversation named '{name.strip()}' already exists.")
            return
        self.note(f"Renamed to '{conv.name}'.")
        await self._refresh_sidebar()

    async def _cmd_delete(self, name: str | None) -> None:
        if name is None:
            target = await self.store.get(self.active_id or "")
        else:
            target = await self.store.get_by_name(name)
        if target is None:
            self.note(f"No conversation named '{name}'.")
            return
        self.sessions.discard(target.id)  # cancels its in-flight turn, if any
        await self.store.delete(target.id)  # local mapping only (STO-005)
        views = self.query(f"#t-{target.id}")
        if views:
            await views.first().remove()
        remaining = await self.store.list()
        if target.id == self.active_id or not remaining:
            if not remaining:
                remaining = [await self.store.create(DEFAULT_CONVERSATION)]
            await self._activate(remaining[0], resumed=remaining[0].thread_id)
        else:
            await self._refresh_sidebar()
        self.note(f"Forgot '{target.name}' locally — its history stays on the server.")

    def _cmd_help(self) -> None:
        lines = ["Commands:"]
        lines += [f"  {c.usage:<16} {c.summary}" for c in COMMANDS]
        lines += [
            "Keys:",
            f"  {self.settings.cancel_key:<16} Cancel the answer in progress",
            "  ctrl+n           New conversation",
            "  tab              Move between the sidebar and the composer",
            "  ctrl+q           Quit",
        ]
        self.note("\n".join(lines))
