from pathlib import Path


ROOT = Path(__file__).resolve().parent
CURRENT_TEST = Path(__file__).resolve()

SKIP_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    "node_modules",
    "dist",
    "build",
}

TEXT_EXTENSIONS = {
    ".py", ".json", ".md", ".txt", ".yaml", ".yml",
    ".toml", ".ini", ".cfg", ".sql", ".env", ".sh",
    ".ps1", ".bat", ".xml", ".html", ".css", ".js",
    ".ts", ".tsx", ".jsx", ".csv", ".log", ".lock",
}

SPECIAL_FILES = {
    "Dockerfile",
    "Makefile",
    "Procfile",
    ".gitignore",
    ".dockerignore",
    ".gitattributes",
}

MOJIBAKE_MARKERS = (
    "РћС‚",
    "РќРµ",
    "РµС",
    "РѕС",
    "Р°С",
    "РёС",
    "РїС",
    "РЅР",
    "СЃ",
    "С‚",
    "СЂ",
    "СЏ",
    "С‹",
    "С‘",
    "�",
)


def test_project_text_files_encoding():
    """Проверяет UTF-8 и очевидные признаки повреждения текста во всём проекте."""

    checked = 0
    problems = []

    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue

        if path.resolve() == CURRENT_TEST:
            continue

        if any(part in SKIP_DIRS for part in path.relative_to(ROOT).parts):
            continue

        is_env_file = path.name == ".env" or path.name.startswith(".env.")
        is_text_file = (
            path.suffix.lower() in TEXT_EXTENSIONS
            or path.name in SPECIAL_FILES
            or is_env_file
        )

        if not is_text_file:
            continue

        try:
            content = path.read_bytes().decode("utf-8-sig")
            checked += 1

        except UnicodeDecodeError as error:
            problems.append(
                f"{path.relative_to(ROOT)}: ошибка UTF-8: {error}"
            )
            continue

        for line_number, line in enumerate(content.splitlines(), start=1):
            found = [
                marker
                for marker in MOJIBAKE_MARKERS
                if marker in line
            ]

            if found:
                problems.append(
                    f"{path.relative_to(ROOT)}, строка {line_number}: "
                    f"подозрительные маркеры {found}; текст: {line.strip()[:180]}"
                )

    assert not problems, (
        f"Проверено файлов: {checked}\n"
        "Обнаружены возможные проблемы кодировки:\n"
        + "\n".join(problems)
    )

    print(f"\nПроверка кодировки: успешно. Проверено файлов: {checked}")
