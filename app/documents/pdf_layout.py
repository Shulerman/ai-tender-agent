from __future__ import annotations


def _group_words_into_lines(words: list[dict], y_tolerance: float = 2.5) -> list[dict]:
    lines = []

    for word in sorted(words, key=lambda item: (item["top"], item["x0"])):
        target = next(
            (
                line
                for line in reversed(lines)
                if abs(line["top"] - word["top"]) <= y_tolerance
            ),
            None,
        )

        if target is None:
            target = {"top": word["top"], "words": []}
            lines.append(target)

        target["words"].append(word)

    for line in lines:
        line["words"].sort(key=lambda item: item["x0"])
        line["text"] = " ".join(word["text"] for word in line["words"])

    return lines


def _cluster_line_starts(
    lines: list[dict],
    x_tolerance: float = 4.5,
    min_line_count: int = 3,
) -> list[float]:
    clusters = []

    for line_index, line in enumerate(lines):
        seen = set()

        for word in line["words"]:
            x = float(word["x0"])
            cluster_index = next(
                (
                    index
                    for index, cluster in enumerate(clusters)
                    if abs(cluster["anchor"] - x) <= x_tolerance
                ),
                None,
            )

            if cluster_index is None:
                clusters.append({
                    "positions": [x],
                    "line_indexes": {line_index},
                    "anchor": x,
                })
                continue

            cluster = clusters[cluster_index]
            cluster["positions"].append(x)
            cluster["line_indexes"].add(line_index)
            cluster["anchor"] = sum(cluster["positions"]) / len(
                cluster["positions"]
            )
            seen.add(cluster_index)

    return sorted(
        round(cluster["anchor"], 1)
        for cluster in clusters
        if len(cluster["line_indexes"]) >= min_line_count
    )


def _line_anchor_hits(
    line: dict,
    anchors: list[float],
    x_tolerance: float = 4.5,
) -> list[float]:
    hits = set()

    for word in line["words"]:
        x = float(word["x0"])
        nearest = min(anchors, key=lambda anchor: abs(anchor - x), default=None)

        if nearest is not None and abs(nearest - x) <= x_tolerance:
            hits.add(nearest)

    return sorted(hits)


def detect_table_regions(
    page,
    min_anchor_count: int = 3,
    min_repeated_lines: int = 3,
    max_intervening_lines: int = 2,
    x_tolerance: float = 4.5,
) -> list[dict]:
    """
    Ищет отдельные таблицы по профилю координат начала ячеек.
    Переносы и строки с пустыми ячейками сохраняются внутри области.
    """
    words = page.extract_words(x_tolerance=2, y_tolerance=3) or []
    lines = _group_words_into_lines(words)

    if len(lines) < min_repeated_lines:
        return []

    candidates = {}

    for seed in lines:
        seed_anchors = sorted({
            round(float(word["x0"]), 1)
            for word in seed["words"]
        })

        if len(seed_anchors) < min_anchor_count:
            continue

        matching = [
            index
            for index, line in enumerate(lines)
            if len(_line_anchor_hits(line, seed_anchors, x_tolerance))
            >= min_anchor_count
        ]

        groups = []
        current = []

        for index in matching:
            if current and index - current[-1] - 1 > max_intervening_lines:
                if len(current) >= min_repeated_lines:
                    groups.append(current)
                current = []
            current.append(index)

        if len(current) >= min_repeated_lines:
            groups.append(current)

        for group in groups:
            key = tuple(group)
            candidates[key] = group

    valid = []

    for group in candidates.values():
        first_index, last_index = group[0], group[-1]
        region_lines = lines[first_index:last_index + 1]

        anchors = _cluster_line_starts(
            [lines[index] for index in group],
            x_tolerance=x_tolerance,
            min_line_count=min_repeated_lines,
        )

        if len(anchors) < min_anchor_count:
            continue

        valid.append({
            "group": group,
            "anchors": anchors,
            "region_lines": region_lines,
            "first": first_index,
            "last": last_index,
        })

    # Убираем вложенные варианты одного профиля, оставляя наиболее
    # протяжённую последовательность повторяющихся строк.
    valid.sort(
        key=lambda item: (
            len(item["group"]),
            item["last"] - item["first"],
        ),
        reverse=True,
    )

    selected = []
    for item in valid:
        overlaps = any(
            not (
                item["last"] < existing["first"]
                or item["first"] > existing["last"]
            )
            for existing in selected
        )
        if not overlaps:
            selected.append(item)

    selected.sort(key=lambda item: item["first"])

    regions = []

    for region_number, item in enumerate(selected, start=1):
        region_lines = item["region_lines"]

        regions.append({
            "region_number": region_number,
            "top": min(line["top"] for line in region_lines),
            "bottom": max(
                max(word["bottom"] for word in line["words"])
                for line in region_lines
            ),
            "anchors": item["anchors"],
            "candidate_line_indexes": [
                index - item["first"] for index in item["group"]
            ],
            "lines": [
                {
                    "top": line["top"],
                    "text": line["text"],
                    "anchor_hits": _line_anchor_hits(
                        line, item["anchors"], x_tolerance
                    ),
                    "words": [
                        {
                            "text": word["text"],
                            "x0": word["x0"],
                            "x1": word["x1"],
                            "top": word["top"],
                            "bottom": word["bottom"],
                        }
                        for word in line["words"]
                    ],
                }
                for line in region_lines
            ],
        })

    return regions
