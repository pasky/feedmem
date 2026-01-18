"""TUI for interactive search results browsing using urwid."""

import asyncio
import webbrowser
from collections.abc import Callable

import urwid  # type: ignore[import-untyped]

from feedmem import db


class TweetListBox(urwid.ListBox):
    def __init__(self, body: urwid.ListWalker, on_select: Callable[[int], None]) -> None:
        super().__init__(body)
        self.on_select = on_select

    def keypress(self, size: tuple[int, int], key: str) -> str | None:
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
        return super().keypress(size, key)

    def _move_focus(self, delta: int, body_len: int) -> None:
        try:
            pos: int = self.focus_position
            new_pos = max(0, min(body_len - 1, pos + delta))
            if new_pos != pos:
                self.focus_position = new_pos
                self.on_select(new_pos)
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
    ) -> None:
        self.results = results
        self.format_fn = format_fn
        self.loop: urwid.MainLoop | None = None

        self.list_walker = urwid.SimpleFocusListWalker(
            [self._make_list_item(i, r) for i, r in enumerate(results)]
        )
        self.tweet_list = TweetListBox(self.list_walker, self._on_select)

        self.detail_walker = urwid.SimpleFocusListWalker([urwid.Text("")])
        self.detail_box = DetailBox(self.detail_walker)

        list_height = min(len(results) + 1, 12)
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
        content = r["content"].replace("\n", " ")
        itype = r.get("interaction_type", "")
        if itype:
            markup = [("itype", f"[{itype}] "), ("handle", f"@{handle}"), f": {content}"]
        else:
            markup = [("handle", f"@{handle}"), f": {content}"]
        return urwid.AttrMap(
            urwid.Text(markup, wrap="clip"),  # type: ignore[arg-type]
            None,
            focus_map={"itype": "itype_hl", "handle": "handle_hl", None: "highlight"},
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
            ("itype", "dark cyan", ""),
            ("handle", "yellow", ""),
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

    async def setup() -> tuple[list[db.SearchResult], dict[str, str]]:
        conn = await db.init_db()
        try:
            results = await db.search_tweets(
                conn, query, interaction_type=interaction_type, limit=limit
            )
            cache: dict[str, str] = {}
            for r in results:
                cache[r["id"]] = await format_with_refs(conn, r, verbose=True)
            return results, cache
        finally:
            await conn.close()

    results, cache = asyncio.run(setup())

    if not results:
        print("No results found.")
        return

    def format_fn(r: db.SearchResult) -> str:
        return cache[r["id"]]

    app = SearchTUI(results, format_fn)
    app.run()
