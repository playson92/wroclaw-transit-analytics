"""Live Chromium, real Streamlit and the Compose PostgreSQL database."""

import json
import os
import re
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

from wroclaw_transit_analytics.dashboard.formatting import number

pytestmark = pytest.mark.browser


def test_live_views_filters_refresh_and_screenshots():
    url = os.environ.get("WTA_BROWSER_URL")
    if not url:
        pytest.skip("Live browser NOT_RUN: WTA_BROWSER_URL unset")
    output = Path(os.environ["WTA_BROWSER_EVIDENCE"])
    output.mkdir(parents=True, exist_ok=True)
    evidence = json.loads(Path(os.environ["WTA_BROWSER_EXPECTED"]).read_text(encoding="utf-8"))
    kind = "real" if "real-smoke" in os.environ["WTA_BROWSER_EXPECTED"] else "demo"
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1050}, device_scale_factor=1)
        errors = []
        page.on("pageerror", lambda error: errors.append(type(error).__name__))
        page.goto(url)
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
        page.get_by_role("radio", name="Linia / punkt zatrzymania", exact=True).check()
        expect(
            page.get_by_role("heading", name="Linia / punkt zatrzymania", exact=True)
        ).to_be_visible()
        selects = page.get_by_test_id("stSelectbox")
        route = selects.filter(has=page.get_by_text("Linia", exact=True)).get_by_role("combobox")
        if kind == "real":
            route.click()
            page.get_by_role(
                "option",
                name=re.compile(
                    "route_id=" + re.escape(evidence["top_routes"][0]["route_id"]) + "$"
                ),
            ).click()
        expect(page.get_by_test_id("stDataFrame").first).to_be_visible(timeout=30000)
        before = page.get_by_test_id("stDataFrame").first.inner_text()
        initial_route = route.inner_text()
        if kind == "demo":
            route.click()
            page.get_by_role("option", name="D2 · route_id=D2", exact=True).click()
            expect(route).to_contain_text("D2")
            # A visible known time is derived from gold; changing route must change this value.
            expect(
                page.get_by_text("Pierwszy znany czas (pierwszy dzień): 23:50:00", exact=True)
            ).to_be_visible(timeout=30000)
        page.screenshot(path=str(output / f"{kind}-line-point.png"), full_page=True)
        filters = {
            "initial_route": initial_route,
            "selected_route": route.inner_text(),
            "selectboxes": selects.all_inner_texts(),
            "initial_table_text": before,
        }
        page.get_by_role("radio", name="Dane i jakość", exact=True).check()
        expect(page.get_by_role("heading", name="Dane i jakość", exact=True)).to_be_visible()
        expect(
            page.get_by_text("dataset_id: " + evidence["dataset_id"], exact=True)
        ).to_be_visible()
        expect(
            page.get_by_text("analysis_id: " + evidence["analysis_id"], exact=True)
        ).to_be_visible()
        page.screenshot(path=str(output / f"{kind}-quality.png"), full_page=True)
        page.get_by_role("radio", name="Przegląd sieci", exact=True).check()
        page.get_by_role("button", name="Odśwież dane").click()
        expect(page.get_by_test_id("stMetricValue").first).to_have_text(number(expected["trips"]))
        page.reload()
        expect(page.get_by_test_id("stMetricValue").first).to_have_text(
            number(expected["trips"]), timeout=30000
        )
        assert not errors
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
