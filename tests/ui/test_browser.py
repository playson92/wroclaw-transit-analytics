"""Live Chromium, real Streamlit and the Compose PostgreSQL database."""

import json
import os
import re
from pathlib import Path

import pytest
from tests.ui.browser_network import protect_local_browser
from tests.ui.test_explorer_browser import select_dataset

from wroclaw_transit_analytics.dashboard.formatting import number, service_time

pytestmark = pytest.mark.browser


def test_live_views_filters_refresh_and_screenshots():
    from playwright.sync_api import expect, sync_playwright

    url = os.environ.get("WTA_BROWSER_URL")
    if not url:
        pytest.skip("Live browser NOT_RUN: WTA_BROWSER_URL unset")
    output = Path(os.environ["WTA_BROWSER_EVIDENCE"])
    output.mkdir(parents=True, exist_ok=True)
    evidence = json.loads(Path(os.environ["WTA_BROWSER_EXPECTED"]).read_text(encoding="utf-8"))
    kind = "real" if "real-smoke" in os.environ["WTA_BROWSER_EXPECTED"] else "demo"
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=os.environ.get("WTA_BROWSER_CHANNEL"))
        page = browser.new_page(viewport={"width": 1440, "height": 1050}, device_scale_factor=1)
        public_requests = protect_local_browser(page, url)
        errors = []
        page.on("pageerror", lambda error: errors.append(type(error).__name__))
        page.goto(url)
        select_dataset(page, evidence["dataset_id"])
        page.get_by_test_id("stButtonGroup").get_by_text("Analityka", exact=True).click()
        expect(page.get_by_role("heading", name="Przegląd sieci", exact=True)).to_be_visible(
            timeout=60000
        )
        expected = evidence["expected_ui_kpi"]
        metrics = page.get_by_test_id("stMetricValue")
        for i, key in enumerate(("trips", "departures", "active_routes", "served_stops")):
            expect(metrics.nth(i)).to_have_text(number(expected[key]), timeout=30000)
        if kind == "demo":
            expect(
                page.get_by_text("DANE SYNTETYCZNE — nie rozkład Wrocławia", exact=True)
            ).to_be_visible()
        page.screenshot(path=str(output / f"{kind}-overview.png"), full_page=True)
        page.get_by_test_id("stButtonGroup").get_by_text(
            "Linia / punkt zatrzymania", exact=True
        ).click()
        expect(
            page.get_by_role("heading", name="Linia / punkt zatrzymania", exact=True)
        ).to_be_visible()
        selects = page.get_by_test_id("stSelectbox")
        route = selects.filter(has=page.get_by_text("Linia", exact=True)).get_by_role("combobox")
        if kind == "real":
            route.click()
            route.fill(evidence["group_selection"]["route_id"])
            page.get_by_role(
                "option",
                name=re.compile(
                    "route_id=" + re.escape(evidence["top_routes"][0]["route_id"]) + "$"
                ),
            ).click()
            stop = selects.filter(
                has=page.get_by_text("Punkt zatrzymania", exact=True)
            ).get_by_role("combobox")
            stop.click()
            stop.fill(evidence["group_selection"]["stop_id"])
            page.get_by_role(
                "option",
                name=re.compile(
                    "stop_id=" + re.escape(evidence["group_selection"]["stop_id"]) + "$"
                ),
            ).click()
            expect(
                page.get_by_text(
                    "Pierwszy znany czas (pierwszy dzień): "
                    + service_time(evidence["group_selection"]["first_departure_seconds"]),
                    exact=True,
                )
            ).to_be_visible(timeout=30000)
        expect(page.get_by_test_id("stDataFrame").first).to_be_visible(timeout=30000)
        before = page.get_by_test_id("stDataFrame").first.inner_text()
        initial_route = route.get_attribute("aria-label")
        if kind == "demo":
            expect(
                page.get_by_text("Pierwszy znany czas (pierwszy dzień): 08:00:00", exact=True)
            ).to_be_visible()
            route.click()
            page.get_by_role("option", name="D2 · route_id=D2", exact=True).click()
            expect(route).to_have_attribute("aria-label", re.compile("Selected D2"))
            # A visible known time is derived from gold; changing route must change this value.
            expect(
                page.get_by_text("Pierwszy znany czas (pierwszy dzień): 23:50:00", exact=True)
            ).to_be_visible(timeout=30000)
        if kind == "demo":
            stop = selects.filter(
                has=page.get_by_text("Punkt zatrzymania", exact=True)
            ).get_by_role("combobox")
            stop.click()
            page.get_by_role("option", name="Demo Plac · stop_id=NA", exact=True).click()
            expect(
                page.get_by_text("Pierwszy znany czas (pierwszy dzień): 24:10:00", exact=True)
            ).to_be_visible(timeout=30000)
        page.screenshot(path=str(output / f"{kind}-line-point.png"), full_page=True)
        filters = {
            "initial_route": initial_route,
            "selected_route": route.get_attribute("aria-label"),
            "selectboxes": selects.all_inner_texts(),
            "initial_table_text": before,
        }
        page.get_by_role(
            "heading", name="Odstępy — statystyki dzienne [sekundy]", exact=True
        ).scroll_into_view_if_needed()
        page.screenshot(path=str(output / f"{kind}-headways.png"), full_page=True)
        page.get_by_test_id("stButtonGroup").get_by_text("Dane", exact=True).click()
        expect(page.get_by_role("heading", name="Dane", exact=True)).to_be_visible()
        page.get_by_text("Identyfikatory i hash", exact=True).click()
        expect(
            page.get_by_text("dataset_id: " + evidence["dataset_id"], exact=True)
        ).to_be_visible()
        expect(
            page.get_by_text("analysis_id: " + evidence["analysis_id"], exact=True)
        ).to_be_visible()
        page.screenshot(path=str(output / f"{kind}-quality.png"), full_page=True)
        page.get_by_test_id("stButtonGroup").get_by_text("Analityka", exact=True).click()
        page.get_by_test_id("stButtonGroup").get_by_text("Przegląd sieci", exact=True).click()
        page.get_by_text("Snapshot i narzędzia", exact=True).click()
        page.get_by_role("button", name="Odśwież dane").click()
        expect(page.get_by_test_id("stMetricValue").first).to_have_text(number(expected["trips"]))
        page.reload()
        select_dataset(page, evidence["dataset_id"])
        page.get_by_test_id("stButtonGroup").get_by_text("Analityka", exact=True).click()
        expect(page.get_by_test_id("stMetricValue").first).to_have_text(
            number(expected["trips"]), timeout=30000
        )
        assert not errors
        assert not public_requests, public_requests
        assert page.get_by_test_id("stException").count() == 0
        assert page.get_by_test_id("stAlert").filter(has_text="Nie udało się").count() == 0
        (output / f"{kind}-browser.json").write_text(
            json.dumps(
                {
                    "status": "PASS",
                    "url": url,
                    "tested_sha": os.environ.get("GITHUB_SHA"),
                    "dataset_id": evidence["dataset_id"],
                    "analysis_id": evidence["analysis_id"],
                    "expected_ui_kpi": expected,
                    "filters": filters,
                    "refresh": "PASS",
                    "reload": "PASS",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        browser.close()
