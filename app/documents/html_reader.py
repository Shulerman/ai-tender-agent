
from html.parser import HTMLParser
from pathlib import Path


class DocumentHTMLParser(HTMLParser):
    """Извлекает текст из HTML, сохраняя структуру документа."""

    BLOCK_TAGS = {
        "p", "div", "br", "h1", "h2", "h3",
        "h4", "h5", "h6", "tr", "li",
        "section", "article", "header", "footer"
    }

    SKIP_TAGS = {"script", "style", "noscript"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP_TAGS:
            self.skip_depth += 1
            return

        if self.skip_depth == 0 and tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP_TAGS and self.skip_depth > 0:
            self.skip_depth -= 1
            return

        if self.skip_depth == 0 and tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if self.skip_depth == 0:
            text = data.strip()
            if text:
                self.parts.append(text)

    def get_text(self):
        return "\n".join(
            part for part in self.parts if part.strip()
        ).strip()


def extract_text_from_html(file_path: str) -> str:
    """Извлекает текст из HTML-документа."""

    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(
            f"Файл не найден: {file_path}"
        )

    if path.suffix.lower() != ".html":
        raise ValueError(
            "Поддерживаются только HTML-документы"
        )

    content = path.read_bytes()

    if content.startswith(b"\xef\xbb\xbf"):
        content = content[3:]

    try:
        html = content.decode("utf-8")
    except UnicodeDecodeError:
        html = content.decode("cp1251", errors="replace")

    parser = DocumentHTMLParser()
    parser.feed(html)

    result = parser.get_text()

    if not result:
        raise ValueError(
            "Не удалось извлечь текст из HTML-документа"
        )

    return result




class DocumentHTMLBlockParser(HTMLParser):
    """Извлекает HTML-блоки в исходном порядке с координатами таблиц."""

    BLOCK_TAGS = {
        "p": "paragraph",
        "h1": "paragraph",
        "h2": "paragraph",
        "h3": "paragraph",
        "h4": "paragraph",
        "h5": "paragraph",
        "h6": "paragraph",
        "li": "list_item",
        "tr": "table_row",
    }

    SKIP_TAGS = {"script", "style", "noscript"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks = []
        self.stack = []
        self.fallback_parts = []
        self.in_head = False
        self.skip_stack = []
        self.table_counter = 0
        self.table_stack = []
        self.table_rows = {}

    def _flush_fallback(self):
        text = " ".join(" ".join(self.fallback_parts).split())
        if text:
            self.blocks.append({
                "locator_type": "text_block",
                "text": text,
            })
        self.fallback_parts = []

    def _emit_frame(self, frame):
        text = " ".join(" ".join(frame["text"]).split())
        if text:
            block = {
                "locator_type": frame["type"],
                "text": text,
            }
            if frame.get("locator_value"):
                block["locator_value"] = frame["locator_value"]
            self.blocks.append(block)

    def _close_frame_at(self, index):
        # Закрываем также незакрытые внутренние блоки сверху вниз.
        while len(self.stack) > index:
            self._emit_frame(self.stack.pop())

    def _close_open_paragraph(self):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index]["tag"] == "p":
                self._close_frame_at(index)
                return

    def handle_starttag(self, tag, attrs):
        if tag == "head":
            self.in_head = True
            return

        if self.in_head:
            return

        if self.skip_stack:
            if tag in self.SKIP_TAGS:
                self.skip_stack.append(tag)
            return

        if tag in self.SKIP_TAGS:
            self.skip_stack.append(tag)
            return

        if tag == "table":
            if any(frame["tag"] == "p" for frame in self.stack):
                self._close_open_paragraph()
            self.table_counter += 1
            self.table_stack.append(self.table_counter)
            self.table_rows[self.table_counter] = 0
            return

        if tag == "p":
            self._close_open_paragraph()

        if tag in {"td", "th"}:
            for frame in reversed(self.stack):
                if frame["tag"] == "tr":
                    if frame["text"]:
                        frame["text"].append(" | ")
                    break
            return

        if tag in self.BLOCK_TAGS:
            self._flush_fallback()
            frame = {
                "tag": tag,
                "type": self.BLOCK_TAGS[tag],
                "text": [],
            }

            if tag == "tr":
                table_number = (
                    self.table_stack[-1]
                    if self.table_stack
                    else self.table_counter + 1
                )
                self.table_rows[table_number] = (
                    self.table_rows.get(table_number, 0) + 1
                )
                frame["locator_value"] = (
                    f"table={table_number};row={self.table_rows[table_number]}"
                )

            self.stack.append(frame)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag == "head":
            self.in_head = False
            return

        if self.in_head:
            return

        if self.skip_stack:
            if tag == self.skip_stack[-1]:
                self.skip_stack.pop()
            return

        if tag == "table":
            if self.table_stack:
                self.table_stack.pop()
            return

        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index]["tag"] == tag:
                self._close_frame_at(index)
                break

        if tag in self.BLOCK_TAGS:
            self._flush_fallback()

    def handle_data(self, data):
        if self.in_head or self.skip_stack:
            return

        text = data.strip()
        if not text:
            return

        if self.stack:
            # Текст относится к ближайшему открытому блоку.
            self.stack[-1]["text"].append(text)
        else:
            self.fallback_parts.append(text)

    def get_blocks(self):
        while self.stack:
            self._emit_frame(self.stack.pop())

        self._flush_fallback()

        counters = {}
        result = []

        for block in self.blocks:
            locator_type = block["locator_type"]
            counters[locator_type] = counters.get(locator_type, 0) + 1

            result.append({
                "locator_type": locator_type,
                "locator_value": block.get(
                    "locator_value", str(counters[locator_type])
                ),
                "text": block["text"],
            })

        return result

def extract_blocks_from_html(file_path: str) -> list[dict]:
    """Извлекает HTML-блоки с сохранением типа и порядкового номера."""

    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"Файл не найден: {file_path}")

    if path.suffix.lower() != ".html":
        raise ValueError("Поддерживаются только HTML-документы")

    content = path.read_bytes()

    if content.startswith(b"\xef\xbb\xbf"):
        content = content[3:]

    try:
        html = content.decode("utf-8")
    except UnicodeDecodeError:
        html = content.decode("cp1251", errors="replace")

    parser = DocumentHTMLBlockParser()
    parser.feed(html)
    parser.close()

    blocks = parser.get_blocks()

    if not blocks:
        raise ValueError("Не удалось извлечь текст из HTML-документа")

    return blocks
