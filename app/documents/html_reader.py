
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
