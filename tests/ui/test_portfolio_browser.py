"""Fresh portfolio sample: real local data, four views, map selection, and responsive UI."""

import json
import math
import os
import re
import time
from pathlib import Path

import pytest
from tests.ui.browser_network import protect_local_browser
from tests.ui.test_explorer_browser import (
    choose,
    control,
    select_dataset,
    select_service_day,
    settled,
)
from tests.ui.test_raster_browser import pixel_counts

from wroclaw_transit_analytics.dashboard.formatting import number, service_time
from wroclaw_transit_analytics.dashboard.presentation import SAMPLE_NOTICE
from wroclaw_transit_analytics.explorer.map import deck

pytestmark = pytest.mark.browser


def navigate(page, view):
    settled(page)
    page.get_by_test_id("stButtonGroup").get_by_text(view, exact=True).click()
    settled(page)


def viewport_dimensions(page):
    """Wait for Streamlit's ResizeObserver and chart layout after a viewport change."""
    measure = """(() => {const main=document.querySelector('[data-testid="stMain"]');
        return {scroll:document.documentElement.scrollWidth,width:window.innerWidth,
        mainScroll:main.scrollWidth,mainWidth:main.clientWidth};})()"""
    page.wait_for_function(
        """() => {const main=document.querySelector('[data-testid="stMain"]');
        return document.documentElement.scrollWidth <= window.innerWidth + 1 &&
            main.scrollWidth <= main.clientWidth + 1;}""",
        timeout=15000,
    )
    return page.evaluate(measure)


def choose_course(page, course):
    select_service_day(page, course["day"])
    choose(page, "Rodzaj transportu", "Wszystkie")
    choose(page, "Linia", re.compile("^" + re.escape(course["route_id"]) + " ·"))
    variant = course["source_variant_id"] or course["shape_id"] or course["variant_key"][:6]
    choose(page, "Kierunek / wariant", re.compile("wariant " + re.escape(variant) + " ·"))
    trip_control = control(page, "Konkretny kurs")
    trip_control.click()
    trip_control.fill(course["trip_id"])
    page.get_by_role(
        "option", name=re.compile("trip_id=" + re.escape(course["trip_id"]) + "$")
    ).click()
    settled(page)
    navigate(page, "Kurs")


def assert_course(page, course):
    from playwright.sync_api import expect

    expect(control(page, "Konkretny kurs")).to_have_attribute(
        "aria-label",
        re.compile("trip_id=" + re.escape(course["trip_id"]) + r"\. Konkretny kurs$"),
        timeout=30000,
    )
    expect(
        page.get_by_text(
            f"Początek: {service_time(course['start_seconds'])} · koniec: {service_time(course['end_seconds'])}",
            exact=True,
        )
    ).to_be_visible(timeout=30000)
    expect(
        page.get_by_text(
            f"Kolejność: {course['first_stop_name']} → {course['last_stop_name']} · {course['visits']} wizyt.",
            exact=True,
        )
    ).to_be_visible()
    expect(page.locator(".wta-visit")).to_have_count(course["visits"])
    expect(
        page.get_by_text(
            re.compile(
                "Geometria shapes właściwego kursu · shape_id="
                + re.escape(course["shape_id"])
                + " · "
                + str(course["shape_points"])
                + " punktów"
            )
        )
    ).to_be_visible()
    expect(page.get_by_test_id("stDeckGlJsonChart")).to_be_visible()


def click_marker(page, course):
    """Project a genuine stop using the same recorded geometry, then click the canvas."""
    from playwright.sync_api import expect

    view = deck(course["visits_records"], course["geometry_records"], "", False).initial_view_state
    chart = page.get_by_test_id("stDeckGlJsonChart")
    chart.scroll_into_view_if_needed()
    canvas = chart.locator("canvas").first
    expect(canvas).to_be_visible()
    deadline = time.monotonic() + 15
    while pixel_counts(chart.screenshot())["stop"] <= 20:
        assert time.monotonic() < deadline, "The course stop markers did not paint"
        page.wait_for_timeout(100)
    scale = 512 * 2**view.zoom

    def project(lon, lat):
        return (
            (lon + 180) / 360 * scale,
            (0.5 - math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) / (2 * math.pi)) * scale,
        )

    center_x, center_y = project(view.longitude, view.latitude)
    box = canvas.bounding_box()
    assert box
    current = control(page, "Przystanek").get_attribute("aria-label")
    candidates = []
    for visit in course["visits_records"]:
        if visit["stop_lat"] is None or visit["stop_lon"] is None:
            continue
        x, y = project(visit["stop_lon"], visit["stop_lat"])
        x, y = box["width"] / 2 + x - center_x, box["height"] / 2 + y - center_y
        if 12 < x < box["width"] - 12 and 12 < y < box["height"] - 12:
            candidates.append((visit, x, y))
    assert candidates, "No visible course stop fits the rendered map"
    # Prefer an isolated point: adjacent platforms can share a marker hit area.
    unselected = [c for c in candidates if "stop_id=" + c[0]["stop_id"] not in current]
    candidate = max(
        unselected or candidates,
        key=lambda candidate: min(
            (
                math.hypot(candidate[1] - other[1], candidate[2] - other[2])
                for other in candidates
                if other[0]["stop_id"] != candidate[0]["stop_id"]
            ),
            default=float("inf"),
        ),
    )
    visit, x, y = candidate
    # SwiftShader/software WebGL can paint before its asynchronous picking
    # result is ready. Prove the native hover identifies this exact SQL stop,
    # then make one real click rather than clicking while the pointer arrives.
    page.mouse.move(box["x"] + x, box["y"] + y)
    expect(
        chart.get_by_text(re.compile("stop_id=" + re.escape(visit["stop_id"]) + "$"))
    ).to_be_visible(timeout=15000)
    # A human press spans browser frames. A zero-duration CDP down/up can
    # outrun async software-GPU picking even after the correct hover rendered.
    # The renderer's transparent map-view element intentionally sits above the
    # canvas. Click the visible map surface, letting its normal hit testing run.
    page.mouse.click(box["x"] + x, box["y"] + y, delay=150)
    expect(page.get_by_role("heading", name="Odjazdy z wybranego przystanku")).to_be_visible(
        timeout=30000
    )
    expect(control(page, "Przystanek")).to_have_attribute(
        "aria-label",
        re.compile("stop_id=" + re.escape(visit["stop_id"]) + r"\. Przystanek$"),
        timeout=30000,
    )
    return visit["stop_id"]


def test_portfolio_real_sample_course_views_filters_mobile_and_reload():
    from playwright.sync_api import expect, sync_playwright

    url = os.environ.get("WTA_PORTFOLIO_URL")
    required = os.environ.get("WTA_REQUIRE_PORTFOLIO_BROWSER") == "1"
    if not url and not required:
        pytest.skip("Portfolio browser NOT_RUN: WTA_PORTFOLIO_URL unset")
    assert url, "Required portfolio browser needs WTA_PORTFOLIO_URL"
    expected_path = os.environ.get("WTA_PORTFOLIO_EXPECTED")
    assert expected_path and Path(expected_path).is_file(), "Missing SQL acceptance expectations"
    expected = json.loads(Path(expected_path).read_text(encoding="utf-8"))
    output = Path(os.environ["WTA_PORTFOLIO_EVIDENCE"])
    output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=os.environ.get("WTA_BROWSER_CHANNEL"))
        page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        source_requests = protect_local_browser(page, url)
        page.goto(url)
        expect(page.get_by_role("heading", name="Mapa i kursy", exact=True)).to_be_visible(
            timeout=60000
        )
        select_dataset(page, expected["dataset_id"])
        expect(page.get_by_text(SAMPLE_NOTICE, exact=True)).to_have_count(1)
        expect(page.get_by_test_id("stDateInputField")).to_have_value(
            re.compile(expected["calendar_start"].replace("-", "[-–]")), timeout=30000
        )
        assert_course(page, expected["default"])
        # A selection callback must also update the native detail widget. Return
        # to the same course before changing any route, trip, day or basemap.
        default_clicked = click_marker(page, expected["default"])
        expect(
            page.get_by_test_id("stButtonGroup").last.get_by_test_id(
                "stBaseButton-segmented_controlActive"
            )
        ).to_have_text("Przystanek")
        navigate(page, "Kurs")
        assert_course(page, expected["default"])
        expect(
            page.get_by_test_id("stButtonGroup").last.get_by_test_id(
                "stBaseButton-segmented_controlActive"
            )
        ).to_have_text("Kurs")
        navigate(page, "Przystanek")
        expect(page.get_by_role("heading", name="Odjazdy z wybranego przystanku")).to_be_visible()
        navigate(page, "Kurs")
        assert_course(page, expected["default"])
        page.get_by_role("heading", name="Mapa i kursy", exact=True).hover()
        page.mouse.wheel(0, -4000)
        page.wait_for_timeout(150)
        title_box = page.get_by_role(
            "heading", name="Wrocław Transit Analytics", exact=True
        ).bounding_box()
        assert title_box and title_box["y"] >= 60, "The app title is covered by the native toolbar"
        panel_box = page.locator(".st-key-explorer_controls").bounding_box()
        assert panel_box and 300 <= panel_box["width"] <= 360, panel_box
        stop_box = (
            page.get_by_test_id("stSelectbox")
            .filter(has=page.get_by_text("Przystanek", exact=True))
            .bounding_box()
        )
        assert stop_box and stop_box["y"] + stop_box["height"] <= 900, stop_box
        chart = page.get_by_test_id("stDeckGlJsonChart")
        chart_box = chart.bounding_box()
        assert chart_box and chart_box["y"] < 440 and chart_box["y"] + chart_box["height"] <= 900
        for width, height, name in (
            (1440, 900, "desktop"),
            (1366, 768, "compact-desktop"),
            (1024, 768, "small-window"),
            (390, 844, "mobile"),
        ):
            page.set_viewport_size({"width": width, "height": height})
            expect(chart).to_be_visible()
            dimensions = viewport_dimensions(page)
            assert dimensions["scroll"] <= dimensions["width"] + 1, dimensions
            assert dimensions["mainScroll"] <= dimensions["mainWidth"] + 1, dimensions
            page.screenshot(path=str(output / f"portfolio-{name}.png"), full_page=True)
        page.set_viewport_size({"width": 1440, "height": 900})
        # An unavailable basemap must leave local course data and geometry usable.
        page.get_by_text("Podkład OpenStreetMap", exact=True).click()
        assert_course(page, expected["default"])
        choose_course(page, expected["bus"])
        assert_course(page, expected["bus"])
        page.screenshot(path=str(output / "portfolio-bus-course.png"), full_page=True)
        chosen_stop = expected["bus"]["stops"][-1]
        stop_control = control(page, "Przystanek")
        stop_control.click()
        stop_control.fill(chosen_stop["stop_id"])
        page.get_by_role(
            "option", name=re.compile("stop_id=" + re.escape(chosen_stop["stop_id"]) + "$")
        ).click()
        settled(page)
        navigate(page, "Przystanek")
        expect(page.get_by_role("heading", name="Odjazdy z wybranego przystanku")).to_be_visible()
        expect(page.get_by_test_id("stDataFrame")).to_be_visible()
        page.screenshot(path=str(output / "portfolio-stop-departures.png"), full_page=True)
        navigate(page, "Kurs")
        # Canvas selection is independent from the dropdown selection.
        clicked_stop = click_marker(page, expected["bus"])
        navigate(page, "Kurs")
        assert_course(page, expected["bus"])
        choose_course(page, expected["late"])
        assert_course(page, expected["late"])
        assert expected["late"]["end_seconds"] >= 86400
        page.screenshot(path=str(output / "portfolio-late-course.png"), full_page=True)
        for view in ("Analityka", "Dane", "O projekcie", "Mapa i kursy"):
            navigate(page, view)
            heading = "Przegląd sieci" if view == "Analityka" else view
            expect(page.get_by_role("heading", name=heading, exact=True)).to_be_visible(
                timeout=30000
            )
            expect(page.get_by_text(SAMPLE_NOTICE, exact=True)).to_have_count(1)
            if view == "Analityka":
                for index, key in enumerate(
                    ("trips", "departures", "active_routes", "served_stops")
                ):
                    expect(page.get_by_test_id("stMetricValue").nth(index)).to_have_text(
                        number(expected["kpi"][key]), timeout=30000
                    )
            page.screenshot(
                path=str(output / ("portfolio-" + view.lower().replace(" ", "-") + ".png")),
                full_page=True,
            )
            page.set_viewport_size({"width": 390, "height": 844})
            expect(page.get_by_role("heading", name=heading, exact=True)).to_be_visible()
            mobile_dimensions = viewport_dimensions(page)
            assert mobile_dimensions["scroll"] <= mobile_dimensions["width"] + 1, mobile_dimensions
            assert mobile_dimensions["mainScroll"] <= mobile_dimensions["mainWidth"] + 1, (
                mobile_dimensions
            )
            page.screenshot(
                path=str(output / ("portfolio-mobile-" + view.lower().replace(" ", "-") + ".png")),
                full_page=True,
            )
            page.set_viewport_size({"width": 1440, "height": 900})
        assert_course(page, expected["late"])
        page.reload()
        expect(page.get_by_role("heading", name="Mapa i kursy", exact=True)).to_be_visible(
            timeout=60000
        )
        assert_course(page, expected["default"])
        assert not errors, errors
        assert not source_requests, f"Unexpected public provider requests: {source_requests}"
        assert page.get_by_test_id("stException").count() == 0
        (output / "portfolio-browser.json").write_text(
            json.dumps(
                {
                    "status": "PASS",
                    "tested_sha": os.environ.get("GITHUB_SHA"),
                    "dataset_id": expected["dataset_id"],
                    "analysis_id": expected["analysis_id"],
                    "expected_kpi": expected["kpi"],
                    "default_trip": expected["default"]["trip_id"],
                    "late_trip": expected["late"]["trip_id"],
                    "clicked_stop": clicked_stop,
                    "default_clicked_stop": default_clicked,
                    "return_to_same_course_after_marker": "PASS",
                    "responsive_viewports": [1440, 1366, 1024, 390],
                    "reload": "PASS",
                    "public_source_requests": source_requests,
                    "basemap": "Unavailable public tiles; local course and geometry verified",
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        browser.close()
