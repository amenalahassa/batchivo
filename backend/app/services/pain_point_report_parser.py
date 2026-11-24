"""Read a pain-point report (markdown, French) into import items (spec 007, research R5).

The report lists problems as ``### N. <problem> — <score>/25`` headings under
``##`` sections, each followed by ``- Label : value`` lines. Only those
headings are problems; sections without them ("Signaux faibles", "Couverture",
"Limites") are ignored. The structured list returned here is the same one an
agent sends to ``POST /ideas/import``: this is the only parser of the report.
"""

import re
from typing import Optional

#: ``### 1. Title — 20/25`` (em dash, en dash or hyphen before the score).
PROBLEM_HEADING = re.compile(
    r"^###\s+(?:\d+\.\s*)?(?P<title>.+?)(?:\s+[—–-]\s*(?P<score>\d{1,2})\s*/\s*25)?\s*$"
)
FIELD_LINE = re.compile(r"^\s*[-*]\s+(?P<label>[^:]{1,60}?)\s*:\s*(?P<value>.*)$")
MARKDOWN_LINK = re.compile(r"\[(?P<text>[^\]]*)\]\((?P<url>https?://[^)\s]+)\)")

TAG_LABELS = ("niche", "culture")
EVIDENCE_LABELS = ("preuves",)
#: Lines kept in the idea's summary, in this order.
SUMMARY_LABELS = (
    ("idée produit", "Product idea"),
    ("citation typique", "Typical quote"),
    ("faisabilité impression", "Print feasibility"),
    ("etsy", "Etsy"),
    ("sensibilité", "Sensitivity"),
    ("atout", "Advantage"),
)
MAX_TITLE = 200


def _normalise_label(label: str) -> str:
    return " ".join(label.strip().lower().split())


def _first_tag(value: str) -> Optional[str]:
    """``voiture (intérieur/coffre)`` → ``voiture (intérieur/coffre)``; first item of a list."""
    tag = re.split(r"\s+[·|—–]\s+|,", value.strip())[0]
    tag = re.sub(r"[*_`]", "", tag).strip().lower()
    return tag[:40] or None


def _problem_to_item(title: str, score: Optional[str], fields: list[tuple[str, str]]) -> dict:
    tags: list[str] = []
    evidence: list[str] = []
    summary_lines: list[str] = []
    by_label: dict[str, str] = {}
    for label, value in fields:
        key = _normalise_label(label)
        by_label.setdefault(key, value.strip())
        if key in TAG_LABELS:
            tag = _first_tag(value)
            if tag and tag not in tags:
                tags.append(tag)
        if key in EVIDENCE_LABELS:
            evidence.extend(m.group("url") for m in MARKDOWN_LINK.finditer(value))
    for key, heading in SUMMARY_LABELS:
        if by_label.get(key):
            summary_lines.append(f"**{heading}:** {by_label[key]}")
    if evidence:
        summary_lines.append("**Evidence:** " + " · ".join(evidence))

    clean_title = re.sub(r"\s+", " ", title).strip()
    if len(clean_title) > MAX_TITLE:
        clean_title = clean_title[: MAX_TITLE - 1].rstrip() + "…"
    item: dict = {
        "title": clean_title,
        "summary": "\n\n".join(summary_lines) or None,
        "tags": tags,
        "source_url": evidence[0] if evidence else None,
    }
    if score is not None:
        item["report_score"] = int(score)
    return item


def parse_report(text: str) -> tuple[list[dict], list[str]]:
    """
    Problems of a report as import items, and warnings for the operator.

    Each item: title, summary, tags, source_url (first evidence link) and
    report_score (the heading's total out of 25) when present.
    """
    items: list[dict] = []
    warnings: list[str] = []
    current: Optional[tuple[str, Optional[str]]] = None
    fields: list[tuple[str, str]] = []

    def flush() -> None:
        if current is None:
            return
        title, score = current
        item = _problem_to_item(title, score, fields)
        if score is None:
            warnings.append(f"No score found for “{item['title']}”")
        if item["source_url"] is None:
            warnings.append(f"No evidence link for “{item['title']}”; it cannot be de-duplicated")
        items.append(item)

    for line in text.splitlines():
        if line.startswith("### "):
            flush()
            match = PROBLEM_HEADING.match(line.strip())
            current = (match.group("title"), match.group("score")) if match else None
            fields = []
            continue
        if line.startswith("## ") or line.startswith("# "):
            flush()
            current, fields = None, []
            continue
        if current is not None:
            field = FIELD_LINE.match(line)
            if field:
                fields.append((field.group("label"), field.group("value")))
    flush()

    if not items:
        warnings.append("No problem was found in this text")
    return items, warnings
