"""The pain-point report parser (spec 007, research R5)."""

from pathlib import Path

from app.services.pain_point_report_parser import parse_report

REPORT = Path(__file__).resolve().parents[1] / "fixtures" / "pain_point_report_sample.md"


def _report_items():
    return parse_report(REPORT.read_text(encoding="utf-8"))


def test_problems_of_every_section_are_read():
    items, warnings = _report_items()
    assert warnings == []
    assert [i["report_score"] for i in items] == [20, 19, 18, 15]
    first = items[0]
    assert first["title"].startswith("Petite pièce plastique de voiture cassée")
    assert "20/25" not in first["title"] and not first["title"].startswith("1.")
    assert first["tags"] == ["voiture (intérieur/coffre)"]
    assert first["source_url"] == "https://forum-a.example.org/thread/1"
    assert "**Product idea:** catalogue de pièces" in first["summary"]
    assert "**Typical quote:**" in first["summary"]
    assert "https://forum-b.example.org/thread/2" in first["summary"]


def test_dashes_and_tags():
    items, _ = _report_items()
    assert items[1]["title"] == "Volets roulants : embouts d'axe introuvables"
    assert items[1]["tags"] == ["maison / fenêtres (france)"]
    assert "**Advantage:**" in items[1]["summary"]
    assert items[2]["title"] == "Les tourne-clés ne vont pas sur la vraie clé de la personne"
    assert items[3]["tags"] == ["culture x"]
    assert "**Sensitivity:**" in items[3]["summary"]


def test_weak_signals_and_other_sections_ignored():
    items, _ = _report_items()
    titles = " ".join(i["title"] for i in items)
    assert "congélation" not in titles and "Cale de porte" not in titles
    assert len(items) == 4


def test_missing_score_and_link_are_warned():
    items, warnings = parse_report("## Top 10\n### 1. A problem\n- Niche : home\n")
    assert items == [{"title": "A problem", "summary": None, "tags": ["home"], "source_url": None}]
    assert any("No score" in w for w in warnings)
    assert any("No evidence link" in w for w in warnings)


def test_no_problem_found():
    items, warnings = parse_report("just some text\n- a: b")
    assert items == [] and warnings == ["No problem was found in this text"]


def test_long_title_is_shortened():
    items, _ = parse_report("### 1. " + "x" * 300 + " — 12/25\n")
    assert len(items[0]["title"]) == 200 and items[0]["report_score"] == 12
