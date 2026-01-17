"""TUI for interactive search results browsing."""

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, ListItem, ListView, Static

from feedmem import db


class TweetList(ListView):
    BINDINGS = [
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
    ]


class SearchTUI(App[None]):
    CSS = """
    #results-list {
        height: 1fr;
        border-bottom: solid $primary;
        background: $background;
    }
    #results-list > ListItem {
        background: $background;
    }
    #results-list > ListItem.-highlight {
        background: $surface;
    }
    #detail-view {
        height: 2fr;
        overflow-y: auto;
    }
    .tweet-item {
        height: 1;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("enter", "open_url", "Open in browser"),
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
        yield TweetList(
            *[
                ListItem(Static(self._one_liner(r), classes="tweet-item"), id=f"item-{i}")
                for i, r in enumerate(self.results)
            ],
            id="results-list",
        )
        yield Static("", id="detail-view")
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
            self.query_one("#detail-view", Static).update(formatted)

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
    verbose: bool = False,
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
        await app.run_async()
    finally:
        await conn.close()


def run_tui(
    query: str,
    interaction_type: str | None = None,
    limit: int = 50,
    verbose: bool = False,
) -> None:
    asyncio.run(run_search_tui(query, interaction_type, limit, verbose))
