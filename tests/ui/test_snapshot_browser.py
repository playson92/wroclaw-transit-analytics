"""Mandatory Compose regression: PostgreSQL + Streamlit + two disjoint synthetic feeds."""

import json
import os
import re
from pathlib import Path

import pytest
from tests.ui.test_explorer_browser import choose, control, select_dataset, select_service_day

pytestmark = pytest.mark.browser


def expected_initial(record):
    return record["start"]


def assert_day_and_course(page, record, day):
    from playwright.sync_api import expect

    field = page.get_by_test_id("stDateInputField").last
    separator = "–" if "–" in field.input_value() else "-"
    try:
        expect(field).to_have_value(day.replace("-", separator), timeout=30000)
    except AssertionError:
        output = Path(os.environ["WTA_BROWSER_EVIDENCE"])
        page.screenshot(path=str(output / "snapshot-date-failure.png"), full_page=True)
        (output / "snapshot-date-failure.json").write_text(
            json.dumps(
                {
                    "expected_dataset": record["dataset_id"],
                    "expected_day": day,
                    "visible_day": field.input_value(),
                    "snapshot": control(page, "Snapshot danych").get_attribute("aria-label"),
                    "technical_text": page.get_by_test_id("stText").all_text_contents(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        raise
    # This date is rendered from the same value sent to the SQL reader, not just browser input.
    expect(page.get_by_text(re.compile("Linia .* · " + re.escape(day) + "$"))).to_be_visible(
        timeout=30000
    )
    expect(control(page, "Konkretny kurs")).to_have_attribute(
        "aria-label", re.compile("trip_id=" + record["prefix"] + "_"), timeout=30000
    )
    expect(
        page.get_by_text(re.compile("^Kolejność: " + record["prefix"] + " Demo"))
    ).to_be_visible()
    expect(page.get_by_test_id("stDeckGlJsonChart")).to_be_visible()
    assert page.get_by_text(re.compile("Brak kursów|poza zakresem snapshotu")).count() == 0


def test_disjoint_snapshots_visible_day_sql_course_filters_views_and_reload():
    from playwright.sync_api import expect, sync_playwright

    url = os.environ.get("WTA_BROWSER_URL")
    required = os.environ.get("WTA_REQUIRE_SNAPSHOT_BROWSER") == "1"
    if not url and not required:
        pytest.skip("Compose browser NOT_RUN: WTA_BROWSER_URL unset")
    assert url, "Mandatory snapshot browser requires WTA_BROWSER_URL"
    fixture = os.environ.get("WTA_BROWSER_FIXTURES")
    assert fixture and Path(fixture).is_file(), "Mandatory Compose browser fixture is missing"
    evidence = json.loads(Path(fixture).read_text(encoding="utf-8"))
    assert evidence["version"] == "wta-browser-disjoint-v1"
    a, b = evidence["A"], evidence["B"]
    assert a["data_kind"] == b["data_kind"] == "synthetic_demo"
    assert a["dataset_id"] != b["dataset_id"]
    assert b["end"] < a["start"]
    output = Path(os.environ["WTA_BROWSER_EVIDENCE"])
    output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=os.environ.get("WTA_BROWSER_CHANNEL"))
        page = browser.new_page(viewport={"width": 1440, "height": 1050}, device_scale_factor=1)
        errors, forbidden = [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        # CI exercises timetable geometry without any public OSM traffic or CUI calls.
        page.route("https://tile.openstreetmap.org/**", lambda route: route.abort())

        def reject_cui(route):
            forbidden.append(route.request.url)
            route.abort()

        page.route("https://open-data.cui.wroclaw.pl/**", reject_cui)
        page.goto(url)
        expect(page.get_by_role("heading", name="Mapa i linie", exact=True)).to_be_visible(
            timeout=60000
        )
        select_dataset(page, a["dataset_id"])
        select_service_day(page, "2026-10-12")  # Explicitly outside B's entire calendar.
        choose(page, "Rodzaj transportu", "Autobus")
        choose(page, "Linia", re.compile("^D2 ·"))
        assert_day_and_course(page, a, "2026-10-12")
        search = (
            page.get_by_test_id("stTextInput")
            .filter(has=page.get_by_text("Szukaj linii", exact=True))
            .get_by_role("textbox")
        )
        search.fill("only A matches this invalid search")
        search.press("Tab")
        expect(
            page.get_by_text(re.compile("Brak linii pasujących do wyszukiwania"))
        ).to_be_visible()

        select_dataset(page, b["dataset_id"])
        expect(control(page, "Rodzaj transportu")).to_have_attribute(
            "aria-label", re.compile("Selected Wszystkie"), timeout=30000
        )
        expect(search).to_have_value("")
        expect(
            page.get_by_test_id("stCheckbox")
            .filter(has=page.get_by_text("Obserwacje pojazdów z CUI", exact=True))
            .get_by_role("checkbox")
        ).not_to_be_checked()
        b_initial = expected_initial(b)
        assert_day_and_course(page, b, b_initial)
        choose(page, "Przystanek", re.compile("stop_id=NA$"))
        page.get_by_test_id("stRadio").get_by_text("Przystanek", exact=True).click()
        expect(page.get_by_text("B Demo Plac · stop_id=NA", exact=True)).to_be_visible(
            timeout=30000
        )
        day_field = page.get_by_test_id("stDateInputField").last
        expect(day_field).to_have_value(
            b_initial.replace("-", "–" if "–" in day_field.input_value() else "-")
        )
        page.screenshot(path=str(output / "snapshot-B-after-stop.png"), full_page=True)

        select_service_day(page, "2026-10-01")
        choose(page, "Linia", re.compile("^D2 ·"))
        page.get_by_test_id("stRadio").get_by_text("Kurs", exact=True).click()
        assert_day_and_course(page, b, "2026-10-01")
        expect(
            page.get_by_text("Początek: 23:50:00 · koniec: 25:10:00", exact=True)
        ).to_be_visible()
        choose(page, "Przystanek", re.compile("stop_id=NA$"))
        for view in ("Analityka", "Dane i jakość", "Mapa i linie"):
            page.get_by_test_id("stRadio").get_by_text(view, exact=True).click()
            heading = "Przegląd sieci" if view == "Analityka" else view
            expect(page.get_by_role("heading", name=heading, exact=True)).to_be_visible(
                timeout=30000
            )
        assert_day_and_course(page, b, "2026-10-01")
        expect(control(page, "Linia")).to_have_attribute("aria-label", re.compile("Selected D2"))
        expect(control(page, "Przystanek")).to_have_attribute(
            "aria-label", re.compile("stop_id=NA")
        )
        page.screenshot(path=str(output / "snapshot-B-after-views.png"), full_page=True)

        # Dataset changes also reset hidden map filters while the user stays in analytics.
        page.get_by_test_id("stRadio").get_by_text("Analityka", exact=True).click()
        expect(page.get_by_role("heading", name="Przegląd sieci", exact=True)).to_be_visible()
        select_dataset(page, a["dataset_id"])
        select_dataset(page, b["dataset_id"])
        page.get_by_test_id("stRadio").get_by_text("Mapa i linie", exact=True).click()
        assert_day_and_course(page, b, b_initial)
        expect(control(page, "Rodzaj transportu")).to_have_attribute(
            "aria-label", re.compile("Selected Wszystkie")
        )

        # Clearing a date must stay empty through another real browser rerun.
        day_field.fill("")
        day_field.press("Tab")
        page.keyboard.press("Escape")
        expect(
            page.get_by_text("Wybierz dzień usługi, aby wyświetlić kursy i mapę.", exact=True)
        ).to_be_visible(timeout=30000)
        choose(page, "Rodzaj transportu", "Autobus")
        expect(day_field).to_have_value("")
        expect(page.get_by_test_id("stDeckGlJsonChart")).to_have_count(0)
        select_service_day(page, "2026-10-01")
        assert_day_and_course(page, b, "2026-10-01")

        select_dataset(page, a["dataset_id"])
        a_initial = expected_initial(a)
        assert_day_and_course(page, a, a_initial)
        choose(page, "Przystanek", re.compile("stop_id=NA$"))
        page.get_by_test_id("stRadio").get_by_text("Przystanek", exact=True).click()
        expect(page.get_by_text("A Demo Plac · stop_id=NA", exact=True)).to_be_visible(
            timeout=30000
        )
        page.reload()
        expect(page.get_by_role("heading", name="Mapa i linie", exact=True)).to_be_visible(
            timeout=60000
        )
        select_dataset(page, b["dataset_id"])
        assert_day_and_course(page, b, b_initial)
        page.screenshot(path=str(output / "snapshot-B-after-reload.png"), full_page=True)
        page.set_viewport_size({"width": 1024, "height": 900})
        assert_day_and_course(page, b, b_initial)
        page.screenshot(path=str(output / "snapshot-B-small-window.png"), full_page=True)
        assert not errors, errors
        assert not forbidden, "Schedule navigation unexpectedly fetched CUI/GTFS"
        assert page.get_by_test_id("stException").count() == 0
        assert page.get_by_test_id("stAlert").filter(has_text="Nie udało się").count() == 0
        (output / "snapshot-browser.json").write_text(
            json.dumps(
                {
                    "status": "PASS",
                    "tested_sha": os.environ.get("GITHUB_SHA"),
                    "A": a["dataset_id"],
                    "B": b["dataset_id"],
                    "A_selected_day": "2026-10-12",
                    "B_initial_day": b_initial,
                    "after_line_stop_and_views": "PASS",
                    "clear_date": "PASS",
                    "reload": "PASS",
                    "public_source_requests": forbidden,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        browser.close()
