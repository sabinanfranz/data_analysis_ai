from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional

__all__ = ["html_to_markdown", "should_enrich_text", "strip_key_deep"]


def should_enrich_text(text: Optional[str]) -> bool:
    if text is None:
        return True
    if isinstance(text, str):
        stripped = text.strip()
        if stripped == "":
            return True
        # one-line/no-bullet text can benefit from enrichment
        if "\n" not in stripped and ("•" not in stripped and "- " not in stripped and "* " not in stripped):
            return True
    return False


class _MarkdownBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.out: List[str] = []
        self.stack: List[str] = []
        self.list_depth = 0
        # table context stack: each context holds rows (list of row cells) and pending rowspans
        self.table_stack: List[Dict[str, Any]] = []

    # region parsing helpers
    def _append_text_to_cell(self, text: str) -> None:
        if not self.table_stack:
            return
        ctx = self.table_stack[-1]
        if ctx.get("row"):
            for cell in reversed(ctx["row"]):
                if isinstance(cell, dict) and not cell.get("_skip"):
                    cell["text"] += text
                    break

    def handle_starttag(self, tag: str, attrs) -> None:
        t = tag.lower()
        self.stack.append(t)
        if t in {"p", "div", "section", "article", "header", "footer"}:
            self.out.append("\n")
        elif t in {"br"}:
            if self.table_stack:
                self._append_text_to_cell("<br>")
            else:
                self.out.append("\n")
        elif t in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.out.append("\n")
        elif t in {"ul", "ol"}:
            self.list_depth += 1
        elif t == "li":
            indent = "  " * max(self.list_depth - 1, 0)
            bullet = "-" if (self.list_depth % 2 == 1) else "-"
            self.out.append(f"\n{indent}{bullet} ")
        elif t == "blockquote":
            self.out.append("\n> ")
        elif t == "table":
            self.table_stack.append({"rows": [], "row": [], "rowspans": []})
        elif t == "tr":
            if not self.table_stack:
                return
            ctx = self.table_stack[-1]
            ctx["row"] = []
            # inject placeholders for pending rowspans
            if ctx.get("rowspans"):
                placeholders: List[Dict[str, Any]] = []
                for remaining in ctx["rowspans"]:
                    if remaining > 0:
                        placeholders.append({"text": "", "colspan": 1, "rowspan": 1, "_skip": True})
                    else:
                        placeholders.append(None)
                ctx["row"].extend(placeholders)
        elif t in {"td", "th"}:
            if not self.table_stack:
                return
            ctx = self.table_stack[-1]
            colspan = 1
            rowspan = 1
            for k, v in attrs:
                if k.lower() == "colspan":
                    try:
                        colspan = max(int(v), 1)
                    except Exception:
                        colspan = 1
                if k.lower() == "rowspan":
                    try:
                        rowspan = max(int(v), 1)
                    except Exception:
                        rowspan = 1
            ctx["row"].append({"text": "", "colspan": colspan, "rowspan": rowspan})
        elif t == "hr":
            self.out.append("\n----\n")

    def handle_endtag(self, tag: str) -> None:
        if not self.stack:
            return
        t = tag.lower()
        while self.stack and self.stack[-1] != t:
            self.stack.pop()
        if self.stack and self.stack[-1] == t:
            self.stack.pop()

        if t in {"ul", "ol"}:
            self.list_depth = max(self.list_depth - 1, 0)
            self.out.append("\n")
        elif t in {"p", "div", "section", "article", "header", "footer"}:
            self.out.append("\n")
        elif t in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.out.append("\n")
        elif t == "blockquote":
            self.out.append("\n")
        elif t == "tr":
            if not self.table_stack:
                return
            ctx = self.table_stack[-1]
            row_cells = [c for c in ctx.get("row", []) if c is not None]
            ctx.setdefault("rows", []).append(row_cells)
            # compute pending rowspans for next row
            col_spans = sum(cell.get("colspan", 1) or 1 for cell in row_cells) if row_cells else 0
            max_cols = max(col_spans, len(ctx.get("rowspans", [])))
            new_rowspans = [0] * max_cols
            col_idx = 0
            for cell in row_cells:
                colspan = cell.get("colspan", 1) or 1
                rowspan = cell.get("rowspan", 1) or 1
                for i in range(colspan):
                    if col_idx + i >= len(new_rowspans):
                        new_rowspans.append(0)
                    if rowspan > 1:
                        new_rowspans[col_idx + i] = max(new_rowspans[col_idx + i], rowspan - 1)
                col_idx += colspan
            ctx["rowspans"] = new_rowspans
            ctx["row"] = []
        elif t == "table":
            if not self.table_stack:
                return
            ctx = self.table_stack.pop()
            rows_meta = ctx.get("rows", [])
            if not rows_meta:
                return
            md = _table_to_markdown(rows_meta)
            if self.table_stack:
                # nested table → keep inside parent cell with <br> separator
                self._append_text_to_cell((md or "").replace("\n", "<br>"))
            else:
                self.out.append("\n" + md + "\n")

    def handle_data(self, data: str) -> None:
        text = unescape(data).replace("\xa0", " ")
        if self.table_stack:
            self._append_text_to_cell(text)
        else:
            self.out.append(text)

    def handle_entityref(self, name: str) -> None:
        self.handle_data(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self.handle_data(f"&#{name};")
    # endregion


def _clean_cell(val: str) -> str:
    cleaned = str(val).replace("\xa0", " ")
    cleaned = re.sub(r"\s*\n\s*", "<br>", cleaned.strip())
    return cleaned


def _table_to_markdown(rows: List[List[Dict[str, Any]]]) -> str:
    if not rows:
        return ""
    # Determine max columns by colspan totals
    col_count = max(sum(cell.get("colspan", 1) or 1 for cell in row) for row in rows)
    grid: List[List[str]] = []
    pending: List[int] = [0] * col_count
    for row in rows:
        out_row: List[str] = ["" for _ in range(col_count)]
        col_idx = 0
        # apply pending rowspans
        while col_idx < col_count and pending[col_idx] > 0:
            pending[col_idx] -= 1
            col_idx += 1
        for cell in row:
            if cell.get("_skip"):
                continue
            while col_idx < col_count and pending[col_idx] > 0:
                pending[col_idx] -= 1
                col_idx += 1
            colspan = cell.get("colspan", 1) or 1
            rowspan = cell.get("rowspan", 1) or 1
            text = cell.get("text", "")
            if col_idx + colspan > col_count:
                extra = col_idx + colspan - col_count
                out_row.extend([""] * extra)
                pending.extend([0] * extra)
                col_count += extra
            out_row[col_idx] = text
            for i in range(1, colspan):
                out_row[col_idx + i] = ""
            if rowspan > 1:
                for i in range(colspan):
                    pending[col_idx + i] = max(pending[col_idx + i], rowspan - 1)
            col_idx += colspan
            while col_idx < col_count and pending[col_idx] > 0:
                pending[col_idx] -= 1
                col_idx += 1
        grid.append(out_row)
    # append placeholder rows for remaining rowspans
    while any(pending):
        out_row = ["" for _ in range(col_count)]
        for idx in range(col_count):
            if pending[idx] > 0:
                pending[idx] -= 1
        grid.append(out_row)
    header = grid[0]
    separator = ["---"] * len(header)
    lines = ["|" + "|".join(_clean_cell(c) for c in header) + "|", "|" + "|".join(separator) + "|"]
    for row in grid[1:]:
        lines.append("|" + "|".join(_clean_cell(c) for c in row) + "|")
    return "\n".join(lines)


def html_to_markdown(html: str) -> str:
    parser = _MarkdownBuilder()
    parser.feed(html or "")
    text = "".join(parser.out)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def strip_key_deep(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        return {k: strip_key_deep(v, key) for k, v in obj.items() if k != key}
    if isinstance(obj, list):
        return [strip_key_deep(v, key) for v in obj]
    return obj
