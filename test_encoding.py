from pathlib import Path
import re


ROOT = Path(__file__).resolve().parent
CURRENT_TEST = Path(__file__).resolve()

SKIP_DIRS = {
    ".git", ".venv", "__pycache__", ".pytest_cache",
    "node_modules", "dist", "build", ".idea",
}

TEXT_EXTENSIONS = {
    ".py", ".json", ".md", ".txt", ".yaml", ".yml",
    ".toml", ".ini", ".cfg", ".sql", ".sh",
    ".ps1", ".bat", ".xml", ".html", ".css", ".js",
    ".ts", ".tsx", ".jsx", ".csv", ".log", ".lock",
}

SPECIAL_FILES = {
    "Dockerfile", "Makefile", "Procfile",
    ".gitignore", ".dockerignore", ".gitattributes",
}

MOJIBAKE_MARKERS = (
    "\u0420\u045b", "\u0420\u0451", "\u0420\u0452",
    "\u0420\u0453", "\u0420\u0454", "\u0420\u0455",
    "\u0420\u0456", "\u0420\u0457", "\u0420\u0458",
    "\u0420\u0459", "\u0420\u045a", "\u0420\u045c",
    "\u0420\u045e", "\u0420\u045f",
    "\u0421\u0453", "\u0421\u0452", "\u0421\u0459",
    "\u0421\u045a", "\u0421\u045b", "\u0421\u045c",
    "\u0421\u045e", "\u0421\u045f",
    "\ufffd",
)

WESTERN_MOJIBAKE_MARKERS = (
    "\u00d0", "\u00d1", "\u00c3", "\u00c2",
)

MOJIBAKE_PATTERN = re.compile(
    r"(?:[\u0420\u0421][\u0410-\u044f\u0401\u0451]){3,}"
)

QUESTION_MARK_PATTERN = re.compile(
    r"\?{3,}|(?:[А-Яа-яЁё]\?){2,}|(?:\?[А-Яа-яЁё]){2,}"
)


def test_project_text_files_encoding():
    """Check project text files for UTF-8 and common mojibake markers."""

    checked = 0
    problems = []

    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue

        if path.resolve() == CURRENT_TEST:
            continue

        relative_path = path.relative_to(ROOT)

        if any(part in SKIP_DIRS for part in relative_path.parts):
            continue

        if path.name == ".env" or path.name.startswith(".env."):
            continue

        is_text_file = (
            path.suffix.lower() in TEXT_EXTENSIONS
            or path.name in SPECIAL_FILES
        )

        if not is_text_file:
            continue

        try:
            content = path.read_bytes().decode("utf-8-sig")
            checked += 1
        except UnicodeDecodeError as error:
            problems.append(
                f"{relative_path}: invalid UTF-8: {error}"
            )
            continue

        for line_number, line in enumerate(content.splitlines(), start=1):
            found = [
                marker
                for marker in MOJIBAKE_MARKERS
                if marker in line
            ]

            found.extend(
                marker
                for marker in WESTERN_MOJIBAKE_MARKERS
                if marker in line
            )

            if MOJIBAKE_PATTERN.search(line):
                found.append("long Cyrillic mojibake sequence")

            if QUESTION_MARK_PATTERN.search(line):
                found.append("possible question-mark replacement")

            if found:
                problems.append(
                    f"{relative_path}, line {line_number}: "
                    f"suspicious markers {found}; "
                    f"text: {line.strip()[:180]}"
                )

    assert not problems, (
        f"Checked files: {checked}\n"
        "Possible encoding problems detected:\n"
        + "\n".join(problems)
    )

    print(
        f"\nEncoding check passed. "
        f"Files checked: {checked}"
    )
