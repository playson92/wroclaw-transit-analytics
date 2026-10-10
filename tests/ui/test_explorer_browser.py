"""Live interactions with snapshot-selected real bus/tram examples, not HTTP-only smoke."""

import json
import math
import os
import re
from pathlib import Path

import pytest

from wroclaw_transit_analytics.dashboard.formatting import service_time
from wroclaw_transit_analytics.explorer.map import deck

pytestmark = pytest.mark.browser


def control(page, label):
    return (
        page.get_by_test_id("stSelectbox")
        .filter(has=page.get_by_text(label, exact=True))
        .get_by_role("combobox")
        .last
    )


def settled(page):
    """Wait for server deltas before interacting with dependent controls."""
    from playwright.sync_api import expect

    expect(page.get_by_test_id("stApp")).to_have_attribute(
        "data-test-script-state", "notRunning", timeout=30000
    )
    expect(page.locator('[data-stale="true"]')).to_have_count(0, timeout=30000)


def choose(page, label, option):
    settled(page)
    control(page, label).click()
    page.get_by_role("option", name=option, exact=isinstance(option, str)).click()
    settled(page)


def select_dataset(page, dataset_id):
    """Select readable names, verifying the full ID only in technical details."""
    from playwright.sync_api import expect

    def selected():
        return page.get_by_text("Wybrany dataset_id: " + dataset_id, exact=True).count() == 1

    settled(page)
    if selected():
        return
    control(page, "Snapshot danych").click()
    expect(page.get_by_role("option").first).to_be_visible()
    options = page.get_by_role("option").all_text_contents()
    page.keyboard.press("Escape")
    transitions = []
    for label in options:
        # The technical expander is collapsed: inner_text() would return an empty
        # string and make a negative wait succeed before the new sidebar delta.
        previous = page.get_by_text(re.compile("^Wybrany dataset_id: ")).text_content()
        if label in (control(page, "Snapshot danych").get_attribute("aria-label") or ""):
            continue
        choose(page, "Snapshot danych", label)
        expect(control(page, "Snapshot danych")).to_have_attribute(
            "aria-label", re.compile(re.escape(label))
        )
        expect(page.get_by_text(re.compile("^Wybrany dataset_id: "))).not_to_have_text(
            previous, timeout=30000
        )
        # The sidebar delta arrives before the date/filter/map deltas. Wait for
        # the entire rerun instead of clicking another snapshot through stale controls.
        settled(page)
        expect(control(page, "Snapshot danych")).to_have_attribute(
            "aria-label", re.compile(re.escape(label))
        )
        transitions.append(
            {
                "label": label,
                "id": page.get_by_text(re.compile("^Wybrany dataset_id: ")).text_content(),
                "visible_label": control(page, "Snapshot danych").get_attribute("aria-label"),
            }
        )
        if selected():
            return
    raise AssertionError(
        "Expected complete snapshot is absent: "
        + dataset_id
        + "; transitions="
        + json.dumps(transitions, ensure_ascii=False)
    )


def select_service_day(page, iso_day):
    from playwright.sync_api import expect

    day = page.get_by_test_id("stDateInputField").last
    # BaseWeb renders an en dash in this version; use its displayed date format.
    separator = "–" if "–" in day.input_value() else "-"
    displayed = iso_day.replace("-", separator)
    day.fill(displayed)
    day.press("Tab")
    page.keyboard.press("Escape")
    # Editing an empty input uses ordinary hyphens; BaseWeb normalizes the
    # committed date to en dashes. Assert the same date in either rendering.
    expect(day).to_have_value(
        re.compile("^" + "[-–]".join(map(re.escape, iso_day.split("-"))) + "$")
    )
    settled(page)


def test_real_explorer_map_trips_click_filters_and_snapshot():
    from playwright.sync_api import expect, sync_playwright

    url = os.environ.get("WTA_EXPLORER_URL")
    if not url:
        pytest.skip("Live explorer NOT_RUN: WTA_EXPLORER_URL unset")
    expected = json.loads(Path(os.environ["WTA_EXPLORER_EXPECTED"]).read_text(encoding="utf-8"))
    output = Path(os.environ["WTA_EXPLORER_EVIDENCE"])
    output.mkdir(parents=True, exist_ok=True)
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=os.environ.get("WTA_BROWSER_CHANNEL"))
        page = browser.new_page(viewport={"width": 1600, "height": 1200}, device_scale_factor=1)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        # Automated tests never scrape public OSM tiles. Test geometry and its no-basemap fallback.
        page.route("https://tile.openstreetmap.org/**", lambda route: route.abort())
        page.goto(url)
        expect(page.get_by_role("heading", name="Mapa i kursy", exact=True)).to_be_visible(
            timeout=60000
        )
        select_dataset(page, expected["dataset_id"])
        page.get_by_text("Podkład OpenStreetMap", exact=True).click()
        for example in expected["examples"]:
            # Compare with the explicitly recorded service day, independently of today's date.
            select_service_day(page, example["day"])
            mode = "Tramwaj" if example["route"]["route_type"] == 0 else "Autobus"
            choose(page, "Rodzaj transportu", mode)
            choose(page, "Linia", example["route_label"])
            choose(
                page,
                "Kierunek / wariant",
                re.compile(
                    "wariant "
                    + re.escape(
                        example["variant"]["source_variant_id"]
                        or example["variant"]["shape_id"]
                        or example["variant"]["variant_key"][:6]
                    )
                    + " ·"
                ),
            )
            choose(
                page,
                "Konkretny kurs",
                re.compile("trip_id=" + re.escape(example["trip"]["trip_id"]) + "$"),
            )
            page.get_by_test_id("stButtonGroup").get_by_text("Kurs", exact=True).click()
            expect(
                page.get_by_text(
                    f"Początek: {service_time(example['trip']['start_seconds'])} · koniec: {service_time(example['trip']['end_seconds'])}",
                    exact=True,
                )
            ).to_be_visible(timeout=30000)
            expect(
                page.get_by_text(
                    f"Kolejność: {example['visits'][0]['stop_name']} → {example['visits'][-1]['stop_name']} · {len(example['visits'])} wizyt.",
                    exact=True,
                )
            ).to_be_visible()
            expect(
                page.get_by_text(
                    re.compile(
                        "Geometria shapes właściwego kursu · shape_id="
                        + re.escape(example["trip"]["shape_id"])
                        + " ·"
                    )
                )
            ).to_be_visible()
            chart = page.get_by_test_id("stDeckGlJsonChart")
            expect(chart).to_be_visible()
            chart.screenshot(path=str(output / f"real-{mode.lower()}-map.png"))
            page.screenshot(path=str(output / f"real-{mode.lower()}-trip.png"), full_page=True)
            # Click a real projected stop. The callback must select its ID and show departures.
            chart.scroll_into_view_if_needed()
            canvas = chart.locator("canvas").first
            box = canvas.bounding_box()
            assert box is not None
            view = deck(
                example["visits"], example["geometry"], example["visits"][0]["stop_id"], False
            ).initial_view_state
            scale = 512 * 2**view.zoom

            def mercator(lon, lat, scale=scale):
                return (
                    (lon + 180) / 360 * scale,
                    (0.5 - math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) / (2 * math.pi))
                    * scale,
                )

            cx, cy = mercator(view.longitude, view.latitude)
            clicked = None
            for visit in example["visits"]:
                if visit["stop_lat"] is None or visit["stop_lon"] is None:
                    continue
                px, py = mercator(visit["stop_lon"], visit["stop_lat"])
                x, y = box["width"] / 2 + px - cx, box["height"] / 2 + py - cy
                if 12 < x < box["width"] - 12 and 12 < y < box["height"] - 12:
                    page.mouse.click(box["x"] + x, box["y"] + y)
                    try:
                        expect(
                            page.get_by_role(
                                "heading", name="Odjazdy z wybranego przystanku", exact=True
                            )
                        ).to_be_visible(timeout=3000)
                        clicked = visit["stop_id"]
                        break
                    except AssertionError:
                        continue
            assert clicked is not None, "No stop click produced details"
            expect(control(page, "Przystanek")).to_have_attribute(
                "aria-label", re.compile("stop_id=" + re.escape(clicked))
            )
            expect(
                page.get_by_text(re.compile("Odjazdy: [0-9]+ · pierwszy znany:"))
            ).to_be_visible()
            page.screenshot(path=str(output / f"real-{mode.lower()}-stop.png"), full_page=True)
            choose(
                page,
                "Kierunek / wariant",
                re.compile(
                    "wariant "
                    + re.escape(
                        example["other_variant"]["source_variant_id"]
                        or example["other_variant"]["shape_id"]
                        or example["other_variant"]["variant_key"][:6]
                    )
                    + " ·"
                ),
            )
            expect(control(page, "Kierunek / wariant")).not_to_have_attribute(
                "aria-label",
                re.compile(
                    "wariant "
                    + re.escape(
                        example["variant"]["source_variant_id"] or example["variant"]["shape_id"]
                    )
                ),
            )
            results.append(
                {
                    "route_id": example["route"]["route_id"],
                    "mode": mode,
                    "trip_id": example["trip"]["trip_id"],
                    "clicked_stop_id": clicked,
                    "map_trip_stop_consistency": "PASS",
                    "variant_change": "PASS",
                }
            )
        late = expected["late_trip"]
        choose(page, "Rodzaj transportu", "Wszystkie")
        choose(page, "Linia", late["route_label"])
        variants = (
            page.get_by_test_id("stSelectbox")
            .filter(has=page.get_by_text("Kierunek / wariant", exact=True))
            .get_by_role("combobox")
        )
        variants.click()
        page.get_by_role(
            "option",
            name=re.compile(
                "wariant "
                + re.escape(late["trip"]["source_variant_id"] or late["trip"]["shape_id"])
                + " ·"
            ),
        ).click()
        choose(
            page,
            "Konkretny kurs",
            re.compile("trip_id=" + re.escape(late["trip"]["trip_id"]) + "$"),
        )
        page.get_by_test_id("stButtonGroup").get_by_text("Kurs", exact=True).click()
        expect(
            page.get_by_text(
                f"Początek: {service_time(late['trip']['start_seconds'])} · koniec: {service_time(late['trip']['end_seconds'])}",
                exact=True,
            )
        ).to_be_visible(timeout=30000)
        page.screenshot(path=str(output / "real-midnight-trip.png"), full_page=True)
        page.get_by_text("Eksperymentalne źródło CUI", exact=True).click()
        page.get_by_text("Obserwacje pojazdów z CUI", exact=True).click()
        page.get_by_test_id("stButtonGroup").get_by_text("Pojazdy", exact=True).click()
        expect(
            page.get_by_role("heading", name="Pozycje pojazdów — osobne źródło", exact=True)
        ).to_be_visible(timeout=60000)
        expect(
            page.get_by_test_id("stAlert")
            .filter(
                has_text=re.compile("Warunki źródła niepotwierdzone|Źródło pozycji niedostępne")
            )
            .first
        ).to_be_visible()
        page.screenshot(path=str(output / "real-positions-status.png"), full_page=True)
        select_service_day(page, "2026-11-01")
        expect(
            page.get_by_text(re.compile("Wybrany dzień 2026-11-01 jest poza zakresem snapshotu"))
        ).to_be_visible(timeout=30000)
        # Keep the originally reproduced date. The standard demo's calendar is 01–31;
        # 01–07 is its gold analysis, while the disjoint CI fixture has the short calendar.
        select_service_day(page, "2026-10-10")
        choose(page, "Snapshot danych", re.compile("^Demo syntetyczne"))
        expect(control(page, "Linia")).to_have_attribute(
            "aria-label", re.compile("Selected D"), timeout=30000
        )
        day_field = page.get_by_test_id("stDateInputField").last
        separator = "–" if "–" in day_field.input_value() else "-"
        expect(day_field).to_have_value("2026-10-01".replace("-", separator))
        experiment = page.get_by_test_id("stExpander").filter(
            has=page.get_by_text("Eksperymentalne źródło CUI", exact=True)
        )
        was_open = experiment.locator("details").get_attribute("open") is not None
        if not was_open:
            page.get_by_text("Eksperymentalne źródło CUI", exact=True).click()
        expect(
            page.get_by_test_id("stCheckbox")
            .filter(has=page.get_by_text("Obserwacje pojazdów z CUI", exact=True))
            .get_by_role("checkbox")
        ).not_to_be_checked()
        if not was_open:
            page.get_by_text("Eksperymentalne źródło CUI", exact=True).click()
        choose(page, "Linia", re.compile("^D2 ·"))
        expect(day_field).to_have_value("2026-10-01".replace("-", separator))
        expect(
            page.get_by_text(
                "Brak zaimportowanej geometrii shapes dla tego kursu. Pokazujemy przystanki, bez udawania przebiegu ulic lub torowiska.",
                exact=True,
            )
        ).to_be_visible(timeout=30000)
        page.get_by_test_id("stButtonGroup").get_by_text("Kurs", exact=True).click()
        expect(
            page.get_by_role("heading", name="Rozkład konkretnego kursu", exact=True)
        ).to_be_visible()
        page.screenshot(path=str(output / "demo-without-shapes.png"), full_page=True)
        assert page.get_by_test_id("stException").count() == 0
        assert not errors, errors
        select_dataset(page, expected["dataset_id"])
        expect(page.get_by_role("heading", name="Mapa i kursy", exact=True)).to_be_visible()
        (output / "explorer-browser.json").write_text(
            json.dumps(
                {
                    "status": "PASS",
                    "url": url,
                    "real_examples": results,
                    "no_service_day": "2026-11-01",
                    "demo_without_shapes": "PASS",
                    "midnight": "PASS",
                    "dataset_change": "PASS",
                    "positions": "UNCONFIRMED_SOURCE_TIME_AND_TERMS",
                    "page_errors": errors,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        browser.close()
