"""TUI for interactive search results browsing."""

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import ScrollableContainer
from textual.widgets import Footer, ListItem, ListView, Static

from feedmem import db


class TweetList(ListView):
    pass


class DetailView(ScrollableContainer):
    can_focus = True


class SearchTUI(App[None]):
    ENABLE_COMMAND_PALETTE = False

    CSS = """
    Screen {
        background: #000000;
    }
    #results-list {
        border-bottom: solid $primary;
        background: #000000;
    }
    #results-list > ListItem {
        background: #000000;
    }
    #results-list > ListItem.-highlight {
        background: #222222;
    }
    #detail-view {
        background: #000000;
    }
    #detail-content {
        background: #000000;
    }
    .tweet-item {
        height: 1;
    }
    """

    BINDINGS = [
        Binding("j", "nav_down", "Down"),
        Binding("k", "nav_up", "Up"),
        Binding("tab", "focus_next", "Switch", priority=True),
        Binding("enter", "open_url", "Open", priority=True),
        Binding("q", "quit", "Quit"),
        Binding("ctrl+d", "page_down", show=False),
        Binding("ctrl+u", "page_up", show=False),
        Binding("g", "go_top", show=False),
        Binding("G", "go_bottom", show=False),
        Binding("ctrl+z", "suspend_process", show=False),
    ]

    def __init__(
        self,
        results: list[db.SearchResult],
        format_fn: Callable[[db.SearchResult], Coroutine[Any, Any, str]],
    ) -> None:
        super().__init__()
        self.results = results
        self.format_fn = format_fn

    def compose(self) -> ComposeResult:
        list_height = min(len(self.results), self.console.height // 2)
        list_widget = TweetList(
            *[
                ListItem(Static(self._one_liner(r), classes="tweet-item"), id=f"item-{i}")
                for i, r in enumerate(self.results)
            ],
            id="results-list",
        )
        list_widget.styles.height = list_height
        yield list_widget
        yield DetailView(Static("", id="detail-content"), id="detail-view")
        yield Footer()

    def _one_liner(self, r: db.SearchResult) -> str:
        handle = r["author_handle"] or "?"
        content = r["content"].replace("\n", " ")[:80]
        itype = r.get("interaction_type", "")
        prefix = f"[{itype}] " if itype else ""
        return f"{prefix}@{handle}: {content}"

    async def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.item is None:
            return
        idx = int(event.item.id.split("-")[1]) if event.item.id else 0
        if 0 <= idx < len(self.results):
            formatted = await self.format_fn(self.results[idx])
            self.query_one("#detail-content", Static).update(formatted)
            self.query_one("#detail-view", DetailView).scroll_home(animate=False)

    def action_nav_down(self) -> None:
        if isinstance(self.focused, TweetList):
            self.focused.action_cursor_down()
        elif isinstance(self.focused, DetailView):
            self.focused.scroll_down(animate=False)

    def action_nav_up(self) -> None:
        if isinstance(self.focused, TweetList):
            self.focused.action_cursor_up()
        elif isinstance(self.focused, DetailView):
            self.focused.scroll_up(animate=False)

    def action_page_down(self) -> None:
        if isinstance(self.focused, DetailView):
            self.focused.scroll_page_down(animate=False)

    def action_page_up(self) -> None:
        if isinstance(self.focused, DetailView):
            self.focused.scroll_page_up(animate=False)

    def action_go_top(self) -> None:
        if isinstance(self.focused, DetailView):
            self.focused.scroll_home(animate=False)

    def action_go_bottom(self) -> None:
        if isinstance(self.focused, DetailView):
            self.focused.scroll_end(animate=False)

    def action_open_url(self) -> None:
        list_view = self.query_one("#results-list", TweetList)
        child = list_view.highlighted_child
        if child is None or child.id is None:
            return
        idx = int(child.id.split("-")[1])
        if 0 <= idx < len(self.results):
            r = self.results[idx]
            handle = r["author_handle"] or "i"
            url = f"https://x.com/{handle}/status/{r['id']}"
            import webbrowser

            webbrowser.open(url)


async def run_search_tui(
    query: str,
    interaction_type: str | None = None,
    limit: int = 50,
) -> None:
    conn = await db.init_db()
    try:
        results = await db.search_tweets(
            conn, query, interaction_type=interaction_type, limit=limit
        )
        if not results:
            print("No results found.")
            return

        async def format_fn(r: db.SearchResult) -> str:
            from feedmem.cli import format_with_refs

            return await format_with_refs(conn, r, verbose=True)

        app = SearchTUI(results, format_fn)
        await app.run_async(mouse=False)
    finally:
        await conn.close()


def run_tui(
    query: str,
    interaction_type: str | None = None,
    limit: int = 50,
) -> None:
    asyncio.run(run_search_tui(query, interaction_type, limit))
