"""Tests for the interactive search TUI."""

from feedmem import db
from feedmem.tui import SearchTUI


def _result(idx: int, itype: str | None = "like") -> db.SearchResult:
    return {  # type: ignore[typeddict-item]
        "id": str(idx),
        "author_id": "u",
        "author_handle": "alice",
        "author_name": "Alice",
        "content": f"tweet {idx}\nsecond line",
        "created_at": "2024-01-15T10:00:00Z",
        "interaction_type": itype,
        "interaction_timestamp": "2024-02-15T12:00:00Z",
        "media": [],
    }


def test_list_item_columns() -> None:
    results = [_result(0), _result(1, itype=None)]
    tui = SearchTUI(results, lambda r: r["content"])

    def cells(idx: int) -> list[str]:
        columns = tui.list_walker[idx].original_widget  # type: ignore[index]
        return [str(w.text) for w, _ in columns.contents]  # type: ignore[union-attr]

    assert cells(0) == ["2024-01-15 10:00", "like", "@alice", "tweet 0 second line"]
    # tweet with no interaction row (pulled in as a referenced tweet) shows "-"
    assert cells(1)[1] == "-"


def test_incremental_loading() -> None:
    pages = {0: [_result(i) for i in range(3)], 3: [_result(i) for i in range(3, 5)], 5: []}
    calls: list[int] = []

    def load_more(offset: int) -> list[db.SearchResult]:
        calls.append(offset)
        return pages.get(offset, [])

    tui = SearchTUI(list(pages[0]), lambda r: r["content"], load_more)
    assert len(tui.results) == 3

    tui.load_next_page()
    assert [r["id"] for r in tui.results] == ["0", "1", "2", "3", "4"]
    assert len(tui.list_walker) == 5

    tui.load_next_page()
    assert tui.exhausted
    tui.load_next_page()
    assert calls == [3, 5]


def test_no_loader_is_exhausted() -> None:
    tui = SearchTUI([_result(0)], lambda r: r["content"])
    assert tui.exhausted
    tui.load_next_page()
    assert len(tui.results) == 1
