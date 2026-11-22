"""Minimal stdlib VT screen for installer frame tests. Not a full terminal."""

from __future__ import annotations


class Screen:
    """Replay CR, LF, CUU, CPL, CHA, EL, ED, SGR, and private cursor show/hide."""

    def __init__(self, columns: int, rows: int = 48) -> None:
        self.columns = columns
        self.rows = rows
        self.grid = [[" "] * columns for _ in range(rows)]
        self.x = 0
        self.y = 0
        self.cursor_hidden = False

    def set_columns(self, columns: int) -> None:
        columns = max(1, columns)
        rebuilt = []
        for row in self.grid:
            if columns <= len(row):
                rebuilt.append(row[:columns])
            else:
                rebuilt.append(row + [" "] * (columns - len(row)))
        self.grid = rebuilt
        self.columns = columns
        self.x = min(self.x, columns - 1)

    def feed(self, data: str) -> None:
        index = 0
        length = len(data)
        while index < length:
            char = data[index]
            if char == "\x1b" and index + 1 < length and data[index + 1] == "[":
                index = self._csi(data, index + 2)
                continue
            if char == "\x1b" and index + 1 < length and data[index + 1] == "]":
                index = self._osc(data, index + 2)
                continue
            if char == "\n":
                self.y += 1
                self.x = 0
                self._scroll()
                index += 1
                continue
            if char == "\r":
                self.x = 0
                index += 1
                continue
            if char < " ":
                index += 1
                continue
            self._put(char)
            index += 1

    def text(self) -> str:
        lines = ["".join(row).rstrip() for row in self.grid]
        while lines and lines[-1] == "":
            lines.pop()
        if not lines:
            return ""
        return "\n".join(lines) + "\n"

    def _put(self, char: str) -> None:
        if self.x >= self.columns:
            self.y += 1
            self.x = 0
            self._scroll()
        if 0 <= self.y < self.rows:
            self.grid[self.y][self.x] = char
        self.x += 1

    def _scroll(self) -> None:
        while self.y >= self.rows:
            self.grid.pop(0)
            self.grid.append([" "] * self.columns)
            self.y -= 1

    def _osc(self, data: str, index: int) -> int:
        end = data.find("\x1b\\", index)
        if end < 0:
            end = data.find("\x07", index)
            return len(data) if end < 0 else end + 1
        return end + 2

    def _csi(self, data: str, index: int) -> int:
        private = False
        params: list[int] = []
        number = ""
        while index < len(data):
            char = data[index]
            index += 1
            if char.isdigit():
                number += char
                continue
            if char == ";":
                params.append(int(number) if number else 0)
                number = ""
                continue
            if char == "?":
                private = True
                continue
            if number:
                params.append(int(number))
            self._dispatch(private, params, char)
            return index
        return index

    def _dispatch(self, private: bool, params: list[int], final: str) -> None:
        if private and final in {"h", "l"} and params == [25]:
            self.cursor_hidden = final == "l"
            return
        if final == "m":
            return
        count = params[0] if params else 1
        if final == "A":
            self.y = max(0, self.y - max(1, count))
            return
        if final == "F":
            self.y = max(0, self.y - max(1, count))
            self.x = 0
            return
        if final == "G":
            self.x = min(self.columns - 1, max(0, (params[0] if params else 1) - 1))
            return
        if final == "K":
            self._erase_line(params[0] if params else 0)
            return
        if final == "J":
            self._erase_display(params[0] if params else 0)

    def _erase_line(self, mode: int) -> None:
        if not (0 <= self.y < self.rows):
            return
        row = self.grid[self.y]
        if mode == 1:
            for column in range(0, min(self.x + 1, self.columns)):
                row[column] = " "
            return
        if mode == 2:
            for column in range(self.columns):
                row[column] = " "
            return
        for column in range(self.x, self.columns):
            row[column] = " "

    def _erase_display(self, mode: int) -> None:
        if mode == 2:
            self.grid = [[" "] * self.columns for _ in range(self.rows)]
            return
        if mode == 1:
            for row in range(0, min(self.y, self.rows)):
                self.grid[row] = [" "] * self.columns
            self._erase_line(1)
            return
        self._erase_line(0)
        for row in range(self.y + 1, self.rows):
            self.grid[row] = [" "] * self.columns
