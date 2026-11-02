"""``ConversationList`` — local conversations, most recent first (SPEC-TUI-UX-003).

Backed by ``ConversationStore.list()`` (the app passes the rows in);
keyboard navigation is ``ListView``'s own (↑/↓, Enter).
"""

from __future__ import annotations

from collections.abc import Sequence

from textual.message import Message
from textual.widgets import Label, ListItem, ListView

from prismal_tui.session.models import Conversation


class ConversationItem(ListItem):
    def __init__(self, conversation: Conversation, *, busy: bool = False) -> None:
        marker = "… " if busy else ""
        super().__init__(Label(f"{marker}{conversation.name}", markup=False))
        self.conversation_id = conversation.id
        self.conversation_name = conversation.name


class ConversationList(ListView):
    DEFAULT_CSS = """
    ConversationList { width: 28; border-right: solid $panel; }
    """

    class Picked(Message):
        def __init__(self, conversation_id: str) -> None:
            super().__init__()
            self.conversation_id = conversation_id

    def __init__(self) -> None:
        super().__init__(id="sidebar")

    async def show(
        self,
        conversations: Sequence[Conversation],
        active_id: str | None,
        busy_ids: frozenset[str] = frozenset(),
    ) -> None:
        await self.clear()
        items = [ConversationItem(c, busy=c.id in busy_ids) for c in conversations]
        await self.extend(items)
        for index, item in enumerate(items):
            if item.conversation_id == active_id:
                self.index = index
                break

    @property
    def names(self) -> list[str]:
        return [i.conversation_name for i in self.query(ConversationItem)]

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        event.stop()
        item = event.item
        if isinstance(item, ConversationItem):
            self.post_message(self.Picked(item.conversation_id))
