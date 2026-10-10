"""Enabled raster with synthetic tiles on Compose demo; never requests public tiles."""

import io
import json
import math
import os
import re
import time
from collections import Counter
from pathlib import Path

import pytest
from PIL import Image
from tests.ui.test_explorer_browser import choose, control, select_service_day

from wroclaw_transit_analytics.explorer.map import deck

pytestmark = pytest.mark.browser
TILE_COLOR = (210, 50, 190)


def pixel_counts(png):
    with Image.open(io.BytesIO(png)) as image:
        pixels = Counter(zip(*[iter(image.convert("RGB").tobytes())] * 3, strict=True))
    colors = {"raster": TILE_COLOR, "selected": (245, 158, 11), "stop": (15, 118, 110)}
    return {
        name: sum(n for p, n in pixels.items() if all(abs(p[i] - color[i]) <= 3 for i in range(3)))
        for name, color in colors.items()
    }


def marker_region_pixels(png, center):
    # Streamlit's picked-object highlight can override the Pydeck fill color.
    # Check visible colored marker pixels at the actually clicked location.
    x, y = center
    with Image.open(io.BytesIO(png)) as image:
        region = image.convert("RGB").crop((int(x) - 8, int(y) - 8, int(x) + 8, int(y) + 8))
        colors = Counter(zip(*[iter(region.tobytes())] * 3, strict=True))
    return sum(
        n
        for p, n in colors.items()
        if max(p) - min(p) > 10 and any(abs(p[i] - TILE_COLOR[i]) > 3 for i in range(3))
    )


def test_enabled_raster_demo_pixels_markers_and_stop_selection():
    from playwright.sync_api import expect, sync_playwright

    url = os.environ.get("WTA_BROWSER_URL")
    if not url:
        pytest.skip("Compose demo browser NOT_RUN: WTA_BROWSER_URL unset")
    expected = json.loads(Path(os.environ["WTA_BROWSER_EXPECTED"]).read_text(encoding="utf-8"))
    output = Path(os.environ["WTA_BROWSER_EVIDENCE"])
    output.mkdir(parents=True, exist_ok=True)
    tile = io.BytesIO()
    Image.new("RGB", (64, 64), TILE_COLOR).save(tile, format="PNG")
    served = []
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=os.environ.get("WTA_BROWSER_CHANNEL"))
        page = browser.new_page(viewport={"width": 1600, "height": 1200}, device_scale_factor=1)

        def serve_tile(route):
            served.append(route.request.url)
            route.fulfill(status=200, content_type="image/png", body=tile.getvalue())

        page.route("https://tile.openstreetmap.org/**", serve_tile)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(url)
        expect(page.get_by_role("heading", name="Mapa i linie", exact=True)).to_be_visible(
            timeout=60000
        )
        choose(page, "Snapshot danych", re.compile(expected["dataset_id"][-12:] + "$"))
        expect(control(page, "Linia")).to_have_attribute(
            "aria-label", re.compile("Selected D"), timeout=30000
        )
        expect(
            page.get_by_text("DANE SYNTETYCZNE — nie rozkład Wrocławia", exact=True)
        ).to_be_visible()
        select_service_day(page, "2026-10-01")
        expect(page.get_by_text(re.compile("Linia .* · 2026-10-01"))).to_be_visible(timeout=30000)
        choose(page, "Rodzaj transportu", "Wszystkie")
        choose(page, "Linia", re.compile("^D1 ·"))
        choose(page, "Konkretny kurs", re.compile("trip_id=T1$"))
        toggle = (
            page.get_by_test_id("stCheckbox")
            .filter(has=page.get_by_text("Podkład OpenStreetMap", exact=True))
            .get_by_role("checkbox")
        )
        if not toggle.is_checked():
            page.get_by_text("Podkład OpenStreetMap", exact=True).click()
        expect(toggle).to_be_checked()
        chart = page.get_by_test_id("stDeckGlJsonChart")
        expect(chart).to_be_visible()
        chart.scroll_into_view_if_needed()
        deadline = time.monotonic() + 30
        while True:
            png = chart.screenshot()
            counts = pixel_counts(png)
            if counts["raster"] > 10000 and counts["stop"] > 20:
                break
            assert time.monotonic() < deadline, f"Raster/markers not rendered: {counts}, {served}"
            page.wait_for_timeout(200)
        assert served, "No intercepted raster requests"
        (output / "TECHNICAL-synthetic-raster-demo.png").write_bytes(png)
        # Demo has no shapes: verify its real stop markers without inventing a street path.
        expect(page.get_by_text(re.compile("Brak zaimportowanej geometrii shapes"))).to_be_visible()
        visits = [
            {"stop_id": s, "stop_name": s, "stop_lat": lat, "stop_lon": lon}
            for s, lat, lon in (
                ("0001", 51.10, 17.03),
                ("NA", 51.11, 17.04),
                ("NULL", 51.12, 17.05),
            )
        ]
        view = deck(visits, [], "0001", True).initial_view_state
        scale = 512 * 2**view.zoom

        def mercator(lon, lat):
            return (
                (lon + 180) / 360 * scale,
                (0.5 - math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) / (2 * math.pi))
                * scale,
            )

        box = chart.locator("canvas").first.bounding_box()
        assert box is not None
        cx, cy = mercator(view.longitude, view.latitude)
        px, py = mercator(17.04, 51.11)
        x, y = box["width"] / 2 + px - cx, box["height"] / 2 + py - cy
        assert 0 < x < box["width"] and 0 < y < box["height"]
        page.mouse.click(box["x"] + x, box["y"] + y)
        expect(page.get_by_role("heading", name="Odjazdy z wybranego przystanku")).to_be_visible()
        expect(control(page, "Przystanek")).to_have_attribute(
            "aria-label", re.compile("stop_id=NA")
        )
        expect(
            page.get_by_text(re.compile("Odjazdy: [1-9][0-9]* · pierwszy znany:"))
        ).to_be_visible()
        expect(page.get_by_test_id("stDataFrame")).to_be_visible()
        expect(toggle).to_be_checked()
        page.mouse.move(0, 0)
        chart_box = chart.bounding_box()
        assert chart_box is not None
        marker_center = (box["x"] + x - chart_box["x"], box["y"] + y - chart_box["y"])
        deadline = time.monotonic() + 15
        while True:
            selected_png = chart.screenshot()
            selected = pixel_counts(selected_png)
            selected["marker_region"] = marker_region_pixels(selected_png, marker_center)
            if selected["raster"] > 10000 and selected["marker_region"] > 20:
                break
            assert time.monotonic() < deadline, f"Selected marker not rendered: {selected}"
            page.wait_for_timeout(200)
        (output / "TECHNICAL-synthetic-raster-selected-map.png").write_bytes(selected_png)
        page.screenshot(path=str(output / "TECHNICAL-synthetic-raster-stop.png"), full_page=True)
        page.get_by_text("Podkład OpenStreetMap", exact=True).click()
        expect(toggle).not_to_be_checked()
        deadline = time.monotonic() + 15
        while True:
            without_png = chart.screenshot()
            without = pixel_counts(without_png)
            without["marker_region"] = marker_region_pixels(without_png, marker_center)
            if without["raster"] == 0 and without["marker_region"] > 20:
                break
            assert time.monotonic() < deadline, f"Raster-off control failed: {without}"
            page.wait_for_timeout(200)
        assert not errors, errors
        assert page.get_by_test_id("stException").count() == 0
        (output / "raster-render-test.json").write_text(
            json.dumps(
                {
                    "RASTER_RENDER_TEST": "PASS",
                    "REAL_BASEMAP_CHECK": "NOT_TESTED_BY_THIS_TEST",
                    "description": "Technical synthetic magenta tiles, not a map of Wroclaw",
                    "tested_sha": os.environ.get("GITHUB_SHA"),
                    "dataset_id": expected["dataset_id"],
                    "service_day": "2026-10-01",
                    "trip_id": "T1",
                    "rendered_pixels": counts,
                    "selected_stop_pixels": selected,
                    "raster_off_pixels": without,
                    "fulfilled_tile_requests": len(served),
                    "clicked_stop_id": "NA",
                    "demo_shapes": "Absent; stop markers verified",
                    "public_tile_requests": 0,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        browser.close()
