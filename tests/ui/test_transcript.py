"""TUI-02-02/03 — TranscriptView rendering (SPEC-TUI-REN-001..005)."""

from __future__ import annotations

from textual.app import App, ComposeResult

from prismal_tui.widgets.transcript import AssistantTurn, TranscriptView


class Harness(App[None]):
    def compose(self) -> ComposeResult:
        yield TranscriptView()


async def test_fast_stream_redraws_are_bounded_and_lossless() -> None:
    """REN-005: redraws scale with frames, not tokens; REN-002: no loss."""
    deltas = [f"tok{i} " for i in range(2000)]
    app = Harness()
    async with app.run_test() as pilot:
        view = app.query_one(TranscriptView)
        turn = view.begin_turn()
        await pilot.pause()
        for i, d in enumerate(deltas):
            turn.feed(d)
            if i % 100 == 0:
                await pilot.pause()  # let a few frames happen mid-stream
        await pilot.pause()
        assert turn.text == "".join(deltas)
        assert 1 <= turn.redraw_count <= 40, turn.redraw_count
        await turn.finalize()
        assert turn.markdown_sources() == ["".join(deltas)]


async def test_every_delta_is_in_the_next_redraw() -> None:
    app = Harness()
    async with app.run_test() as pilot:
        turn = app.query_one(TranscriptView).begin_turn()
        await pilot.pause()
        turn.feed("a")
        turn.feed("b")
        await pilot.pause()
        segment = turn.children[0]
        assert str(segment.render()) == "ab"


async def test_streaming_text_is_not_parsed_as_markup() -> None:
    app = Harness()
    async with app.run_test() as pilot:
        turn = app.query_one(TranscriptView).begin_turn()
        await pilot.pause()
        turn.feed("[bold]not markup[/bold] [link=x]")
        await pilot.pause()
        assert str(turn.children[0].render()) == "[bold]not markup[/bold] [link=x]"


async def test_finalize_with_note_keeps_partial_and_is_idempotent() -> None:
    app = Harness()
    async with app.run_test() as pilot:
        view = app.query_one(TranscriptView)
        turn = view.begin_turn()
        await pilot.pause()
        turn.feed("partial")
        await turn.finalize(note="— cancelled —")
        await turn.finalize(note="again")
        turn.feed(" ignored")
        await pilot.pause()
        assert turn.markdown_sources() == ["partial"]
        assert view.notes == ["— cancelled —"]


async def test_turn_with_no_text_finalizes_cleanly() -> None:
    app = Harness()
    async with app.run_test() as pilot:
        view = app.query_one(TranscriptView)
        turn: AssistantTurn = view.begin_turn()
        await pilot.pause()
        await turn.finalize(note="Can't reach prismal-server")
        assert turn.markdown_sources() == []
        assert view.notes == ["Can't reach prismal-server"]
