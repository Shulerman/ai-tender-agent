
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
    """Извлекает HTML-блоки с сохранением порядка и типа."""

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
        self.skip_depth = 0
        self.fallback_parts = []

    def _flush_fallback(self):
        text = " ".join(" ".join(self.fallback_parts).split())
        if text:
            self.blocks.append({
                "locator_type": "text_block",
                "text": text,
            })
        self.fallback_parts = []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP_TAGS:
            self.skip_depth += 1
            return

        if self.skip_depth:
            return

        if tag in {"td", "th"} and self.stack:
            for frame in reversed(self.stack):
                if frame["tag"] == "tr":
                    if frame["text"]:
                        frame["text"].append("|")
                    break

        if tag in self.BLOCK_TAGS:
            self._flush_fallback()
            self.stack.append({
                "tag": tag,
                "type": self.BLOCK_TAGS[tag],
                "text": [],
            })

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag in self.SKIP_TAGS and self.skip_depth:
            self.skip_depth -= 1
            return

        if self.skip_depth:
            return

        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index]["tag"] == tag:
                frame = self.stack.pop(index)
                text = " ".join(" ".join(frame["text"]).split())

                if text:
                    self.blocks.append({
                        "locator_type": frame["type"],
                        "text": text,
                    })
                break

        if tag in self.BLOCK_TAGS:
            self._flush_fallback()

    def handle_data(self, data):
        if self.skip_depth:
            return

        text = data.strip()
        if not text:
            return

        if self.stack:
            self.stack[-1]["text"].append(text)
        else:
            self.fallback_parts.append(text)

    def get_blocks(self):
        while self.stack:
            frame = self.stack.pop()
            text = " ".join(" ".join(frame["text"]).split())
            if text:
                self.blocks.append({
                    "locator_type": frame["type"],
                    "text": text,
                })

        self._flush_fallback()

        counters = {}
        result = []

        for block in self.blocks:
            locator_type = block["locator_type"]
            counters[locator_type] = counters.get(locator_type, 0) + 1

            result.append({
                "locator_type": locator_type,
                "locator_value": str(counters[locator_type]),
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
