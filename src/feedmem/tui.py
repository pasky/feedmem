"""TUI for interactive search results browsing using urwid."""

import asyncio
import webbrowser
from collections.abc import Callable

import urwid  # type: ignore[import-untyped]

from feedmem import db


class TweetListBox(urwid.ListBox):
    def __init__(
        self,
        body: urwid.ListWalker,
        on_select: Callable[[int], None],
        on_need_more: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(body)
        self.on_select = on_select
        self.on_need_more = on_need_more

    def keypress(self, size: tuple[int, int], key: str) -> str | None:
        self._maybe_load_more()
        body_len: int = len(self.body)  # type: ignore[arg-type]
        if key in ("j", "down"):
            self._move_focus(1, body_len)
            return None
        if key in ("k", "up"):
            self._move_focus(-1, body_len)
            return None
        if key == "g":
            self._move_focus(-body_len, body_len)
            return None
        if key == "G":
            self._move_focus(body_len, body_len)
            return None
        try:
            before: int | None = self.focus_position
        except IndexError:
            before = None
        result = super().keypress(size, key)
        try:
            after: int | None = self.focus_position
        except IndexError:
            after = None
        if after is not None and after != before:
            self.on_select(after)
        self._maybe_load_more()
        return result

    def _maybe_load_more(self) -> None:
        """Fetch the next page when the focus nears the end of the loaded list."""
        if self.on_need_more is None:
            return
        try:
            pos: int = self.focus_position
        except IndexError:
            return
        body_len: int = len(self.body)  # type: ignore[arg-type]
        if pos >= body_len - 5:
            self.on_need_more()

    def _move_focus(self, delta: int, body_len: int) -> None:
        try:
            pos: int = self.focus_position
            new_pos = max(0, min(body_len - 1, pos + delta))
            if new_pos != pos:
                self.focus_position = new_pos
                self.on_select(new_pos)
                self._maybe_load_more()
        except IndexError:
            pass


class DetailBox(urwid.ListBox):
    def keypress(self, size: tuple[int, int], key: str) -> str | None:
        if key in ("j", "down"):
            return super().keypress(size, "down")
        if key in ("k", "up"):
            return super().keypress(size, "up")
        if key == "ctrl d":
            for _ in range(size[1] // 2):
                super().keypress(size, "down")
            return None
        if key == "ctrl u":
            for _ in range(size[1] // 2):
                super().keypress(size, "up")
            return None
        if key == "g":
            self.set_focus(0)  # type: ignore[arg-type]
            return None
        if key == "G":
            body_len: int = len(self.body)  # type: ignore[arg-type]
            self.set_focus(body_len - 1)  # type: ignore[arg-type]
            return None
        return super().keypress(size, key)


class SearchTUI:
    def __init__(
        self,
        results: list[db.SearchResult],
        format_fn: Callable[[db.SearchResult], str],
        load_more: Callable[[int], list[db.SearchResult]] | None = None,
    ) -> None:
        self.results = results
        self.format_fn = format_fn
        self.load_more = load_more
        self.exhausted = load_more is None
        self.loading = False
        self.loop: urwid.MainLoop | None = None

        self.list_walker = urwid.SimpleFocusListWalker(
            [self._make_list_item(i, r) for i, r in enumerate(results)]
        )
        self.tweet_list = TweetListBox(self.list_walker, self._on_select, self.load_next_page)

        self.detail_walker = urwid.SimpleFocusListWalker([urwid.Text("")])
        self.detail_box = DetailBox(self.detail_walker)

        list_height = 12 if load_more else min(len(results) + 1, 12)
        self.list_box = urwid.BoxAdapter(self.tweet_list, list_height)
        divider = urwid.AttrMap(urwid.Divider("─"), "divider")

        self.pile = urwid.Pile([("pack", self.list_box), ("pack", divider), self.detail_box])
        self.pile.focus_position = 0

        footer = urwid.Text(
            " j/k:nav  tab:switch  enter:open  ctrl-d/u:page  g/G:top/bottom  q:quit"
        )
        self.frame = urwid.Frame(self.pile, footer=urwid.AttrMap(footer, "footer"))

    def _make_list_item(self, idx: int, r: db.SearchResult) -> urwid.Widget:
        handle = r["author_handle"] or "?"
        content = " ".join(r["content"].split())
        itype = r.get("interaction_type") or "-"
        # tweet time (list is ordered by it); fall back to when we saw the interaction
        ts = (r.get("created_at") or r.get("interaction_timestamp") or "").replace("T", " ")[:16]
        columns = urwid.Columns(
            [
                (16, urwid.Text(("ts", ts), wrap="clip")),
                (8, urwid.Text(("itype", itype), wrap="clip")),
                (16, urwid.Text(("handle", f"@{handle}"), wrap="clip")),
                urwid.Text(content, wrap="clip"),
            ],
            dividechars=1,
        )
        return urwid.AttrMap(
            columns,
            None,
            focus_map={
                "ts": "ts_hl",
                "itype": "itype_hl",
                "handle": "handle_hl",
                None: "highlight",
            },
        )

    def load_next_page(self) -> None:
        if self.exhausted or self.loading or self.load_more is None:
            return
        self.loading = True
        try:
            new_results = self.load_more(len(self.results))
        finally:
            self.loading = False
        if not new_results:
            self.exhausted = True
            return
        start = len(self.results)
        self.results.extend(new_results)
        self.list_walker.extend(  # type: ignore[attr-defined]
            [self._make_list_item(start + i, r) for i, r in enumerate(new_results)]
        )

    def _on_select(self, idx: int) -> None:
        self._update_detail(idx)

    def _update_detail(self, idx: int) -> None:
        if 0 <= idx < len(self.results):
            formatted = self.format_fn(self.results[idx])
            lines = formatted.split("\n")
            widgets: list[urwid.Widget] = []
            for i, line in enumerate(lines):
                stripped = line.lstrip().lstrip("│").lstrip()
                if i == 0 or stripped.startswith("[ref]") or stripped.startswith("[own]"):
                    widgets.append(urwid.Text(("detail_header", line)))
                elif stripped.startswith(("┌─", "↩")):
                    widgets.append(urwid.Text(("detail_ref", line)))
                else:
                    widgets.append(urwid.Text(line))
            self.detail_walker[:] = widgets  # type: ignore[index]
            if self.detail_walker:
                self.detail_box.set_focus(0)  # type: ignore[arg-type]

    def _open_url(self) -> None:
        try:
            idx = self.tweet_list.focus_position
            if 0 <= idx < len(self.results):
                r = self.results[idx]
                handle = r["author_handle"] or "i"
                url = f"https://x.com/{handle}/status/{r['id']}"
                webbrowser.open(url)
        except IndexError:
            pass

    def unhandled_input(self, key: str | tuple[str, int, int, int]) -> bool:
        if key == "q":
            raise urwid.ExitMainLoop()
        if key == "tab":
            self.pile.focus_position = 2 if self.pile.focus_position == 0 else 0
            return True
        if key == "enter":
            self._open_url()
            return True
        return False

    def run(self) -> None:
        palette = [
            ("highlight", "black", "light gray"),
            ("footer", "white", "dark blue"),
            ("divider", "white", "dark blue"),
            ("ts", "dark green", ""),
            ("itype", "dark cyan", ""),
            ("handle", "yellow", ""),
            ("ts_hl", "dark green", "light gray"),
            ("itype_hl", "dark cyan", "light gray"),
            ("handle_hl", "yellow", "light gray"),
            ("detail_header", "dark cyan", ""),
            ("detail_ref", "yellow", ""),
        ]
        self.loop = urwid.MainLoop(
            self.frame,
            palette=palette,
            unhandled_input=self.unhandled_input,
            handle_mouse=False,
        )
        if self.results:
            self._update_detail(0)
        self.loop.run()


def run_tui(
    query: str,
    interaction_type: str | None = None,
    limit: int = 50,
) -> None:
    from feedmem.cli import format_with_refs

    cache: dict[str, str] = {}

    async def fetch(offset: int) -> list[db.SearchResult]:
        conn = await db.init_db()
        try:
            results = await db.search_tweets(
                conn, query, interaction_type=interaction_type, limit=limit, offset=offset
            )
            for r in results:
                cache[r["id"]] = await format_with_refs(conn, r, verbose=True)
            return results
        finally:
            await conn.close()

    def load_more(offset: int) -> list[db.SearchResult]:
        return asyncio.run(fetch(offset))

    results = load_more(0)

    if not results:
        print("No results found.")
        return

    def format_fn(r: db.SearchResult) -> str:
        return cache[r["id"]]

    app = SearchTUI(results, format_fn, load_more)
    app.run()
