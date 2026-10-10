"""Shared presentation only: escaped GTFS text, compact cards, and stable layout hooks."""

from html import escape
from typing import Any

import streamlit as st

from .formatting import service_time

SAMPLE_NOTICE = "Próbka archiwalnego rozkładu — wybrane linie, nie cała sieć"
REPOSITORY = "https://github.com/playson92/wroclaw-transit-analytics"
FAVICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
<rect width="32" height="32" rx="7" fill="#12304c"/>
<path d="m9 28 4-6m10 6-4-6" stroke="#fff" stroke-width="2"/>
<rect x="7" y="4" width="18" height="21" rx="5" fill="#008c95"/>
<rect x="10" y="8" width="12" height="9" rx="2" fill="#12304c"/>
<path d="M16 8v9" stroke="#008c95" stroke-width="2"/>
<circle cx="11" cy="21" r="1.5" fill="#fff"/>
<circle cx="21" cy="21" r="1.5" fill="#fff"/>
</svg>"""

# Native config.toml supplies widget colors, borders, and typography. These rules
# arrange our own cards and named containers; they never target generated classes.
STYLE = """
<style>
[data-testid="stMainBlockContainer"] {padding-top: 4rem; padding-bottom: 2rem; max-width: 1600px;}
[data-testid="stMainBlockContainer"] > [data-testid="stVerticalBlock"] {gap: .65rem;}
.st-key-portfolio_header [data-testid="stVerticalBlock"] {gap: .4rem;}
.st-key-portfolio_header h1 {font-size: 1.65rem; padding-top: 0; padding-bottom: .1rem;}
.st-key-portfolio_nav {margin-top: .25rem; margin-bottom: .2rem;}
.st-key-explorer_controls {gap: .4rem; background: #fff;}
.st-key-explorer_controls [data-testid="stWidgetLabel"] {margin-bottom: .15rem;}
.st-key-explorer_controls h3 {font-size: 1.1rem; padding-top: .2rem; padding-bottom: .1rem;}
.st-key-explorer_controls [data-testid="stHeading"] [data-testid="stMarkdownContainer"] {margin-bottom: 0;}
.st-key-explorer_controls label p {font-size: .875rem;}
.st-key-explorer_canvas {gap: .6rem;}
.st-key-explorer_canvas [data-testid="stDeckGlJsonChart"] {border-radius: 12px; overflow: hidden; border: 1px solid #dce4ed;}
.wta-route {display: flex; align-items: center; gap: 14px; min-width: 0;}
.wta-badge {display: inline-flex; justify-content: center; align-items: center; flex-shrink: 0; min-width: 46px; height: 46px; padding: 0 10px; border-radius: 10px; background: #12304c; color: #fff; font-size: 22px; font-weight: 700;}
.wta-route-body {min-width: 0; overflow-wrap: anywhere;}
.wta-route-body strong {display: block; font-size: 1.1rem; color: #12304c;}
.wta-meta {font-size: .85rem; color: #53677d; line-height: 1.5;}
.wta-visits {list-style: none; margin: 0; padding: 0;}
.wta-visit {display: grid; grid-template-columns: 72px 26px minmax(0, 1fr); align-items: start; gap: 8px; padding: 12px 10px; border-bottom: 1px solid #e9eef4; border-radius: 5px;}
.wta-visit.selected {background: #fff3df; border-left: 3px solid #c86a0c;}
.wta-visit-time {font-variant-numeric: tabular-nums; font-weight: 650; color: #12304c; font-size: .9rem;}
.wta-sequence {width: 23px; height: 23px; display: inline-flex; justify-content: center; align-items: center; border-radius: 50%; background: #e1f2f1; color: #086b68; font-size: .75rem;}
.wta-visit-name {overflow-wrap: anywhere; font-size: .95rem; color: #12304c;}
.wta-visit-name small {display: block; font-size: .78rem; color: #53677d; padding-top: 3px;}
@media (min-width: 768px) {
 .st-key-explorer_layout > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:first-child,
 .st-key-explorer_layout > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:first-child,
 .st-key-explorer_layout > [data-testid="stVerticalBlock"] > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:first-child {flex: 0 0 325px; width: 325px; min-width: 300px;}
 .st-key-explorer_layout > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:last-child {flex: 1 1 0; min-width: 0; width: auto;}
}
@media (max-width: 767px) {
 [data-testid="stMainBlockContainer"] {padding: 4rem .9rem 2rem;}
 .st-key-portfolio_header h1 {font-size: 1.4rem;}
 .st-key-portfolio_nav button {font-size: .78rem; padding-left: .55rem; padding-right: .55rem;}
 .wta-visit {grid-template-columns: 64px 24px minmax(0, 1fr); gap: 5px; padding-left: 4px; padding-right: 4px;}
}
</style>
"""


def style() -> None:
    st.html(STYLE)


def route_card(
    route: dict[str, Any],
    headsign: str | None,
    mode: str,
    schedule: tuple[int | None, int | None, int] | None = None,
) -> None:
    """Names originate in external GTFS and must remain escaped text."""
    badge = escape(str(route.get("route_short_name") or "—"))
    direction = escape(str(headsign or route.get("route_long_name") or "Brak opisu kierunku"))
    agency = escape(str(route.get("agency_name") or ""))
    symbol = "🚋" if mode == "Tramwaj" else "🚌" if mode == "Autobus" else "○"
    timing = (
        f" · {service_time(schedule[0])} → {service_time(schedule[1])} · {schedule[2]} wizyt"
        if schedule
        else ""
    )
    st.html(
        f'<div class="wta-route"><span class="wta-badge">{badge}</span>'
        f'<div class="wta-route-body"><strong>{direction}</strong>'
        f'<span class="wta-meta">{symbol} {escape(mode)} · {agency}{escape(timing)}</span></div></div>'
    )


def visit_list(visits: list[dict[str, Any]], selected: str) -> None:
    """Display every ordered visit, including repeat visits to the same stop_id."""
    entries = []
    for visit in visits:
        known = service_time(visit["departure_seconds"])
        name = escape(str(visit["stop_name"]))
        precision = (
            "brak czasu odjazdu"
            if visit["departure_seconds"] is None
            else "czas dokładny"
            if visit["timepoint"]
            else "czas przybliżony"
        )
        pickup = {
            0: "",
            1: " · bez wsiadania",
            2: " · na żądanie telefoniczne",
            3: " · na żądanie",
        }[visit["pickup_type"]]
        selected_class = " selected" if visit["stop_id"] == selected else ""
        selected_text = " · wybrany punkt" if selected_class else ""
        entries.append(
            f'<li class="wta-visit{selected_class}">'
            f'<span class="wta-visit-time">{escape(known)}</span>'
            f'<span class="wta-sequence">{visit["stop_sequence"]}</span>'
            f'<span class="wta-visit-name">{name}<small>{precision.capitalize()}{pickup}{selected_text}</small></span></li>'
        )
    st.html('<ol class="wta-visits">' + "".join(entries) + "</ol>")


def about() -> None:
    st.header("O projekcie")
    st.markdown("### Od pliku GTFS do konkretnego przejazdu")
    st.write(
        "Wrocław Transit Analytics pomaga zrozumieć zapisany rozkład komunikacji: "
        "wybrać linię i kurs, obejrzeć jego przystanki oraz policzyć ofertę przewozową w SQL. "
        "To niezależny projekt portfolio, nie oficjalna aplikacja miasta ani MPK."
    )
    left, right = st.columns(2, gap="large")
    with left:
        with st.container(border=True):
            st.subheader("Jeden pipeline, dwa widoki")
            st.markdown(
                "**GTFS ZIP → walidacja → silver → PostgreSQL → SQL gold → aplikacja**\n\n"
                "Parser zachowuje źródłowe identyfikatory, loader działa transakcyjnie, "
                "a kalendarz uwzględnia wyjątki. Mapa i analityka czytają ten sam snapshot."
            )
            st.caption("Python 3.12 · PostgreSQL 17 · Streamlit · Pydeck · Altair · Docker Compose")
    with right:
        with st.container(border=True):
            st.subheader("Zajrzyj do kodu")
            for title, path in (
                ("Przygotowanie i walidacja danych", "src/wroclaw_transit_analytics/preparation"),
                ("Transakcyjny loader", "src/wroclaw_transit_analytics/database"),
                ("Kalendarz i metryki SQL", "src/wroclaw_transit_analytics/analytics/sql"),
                ("Mapa i szczegóły kursów", "src/wroclaw_transit_analytics/explorer"),
                ("Testy scenariuszy w przeglądarce", "tests/ui"),
            ):
                st.markdown(f"[{title}]({REPOSITORY}/tree/main/{path})")
    st.subheader("Świadome ograniczenia")
    st.write(
        "To zapis rozkładu, bez pomiaru opóźnień i pozycji GPS. "
        "Godzina 25:10 należy do wcześniejszego dnia usługi. Brak czasu lub dnia "
        "poza kalendarzem oznacza brak wiedzy, nie zero. Frequencies i GTFS Flex "
        "nie są rozwijane w metrykach gold. Podkład OpenStreetMap wymaga sieci; "
        "geometria kursów i rozkład działają lokalnie."
    )
    st.caption("Autor: Jonatan Tomaszewicz · kod MIT · dane GTFS zgodnie z licencją źródła")
    st.link_button("Repozytorium i instrukcja uruchomienia", REPOSITORY, icon=":material/code:")
