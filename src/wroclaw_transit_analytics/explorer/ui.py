"""Day → route → direction/stop pattern → trip, with click and keyboard stop selection."""

import hashlib

import pandas as pd
import streamlit as st

from ..dashboard.formatting import service_time
from ..dashboard.presentation import route_card, visit_list
from . import data, positions
from .map import deck

FILTER_KEYS = (
    "explorer_day",
    "explorer_mode",
    "explorer_search",
    "explorer_route",
    "explorer_variant",
    "explorer_trip",
    "explorer_stop",
    "explorer_detail",
    "explorer_basemap",
    "explorer_vehicles",
)


def retain_filters():
    """Keep this view's widget values when Streamlit omits them in another view."""
    for key in FILTER_KEYS:
        if key in st.session_state:
            st.session_state[key] = st.session_state[key]


def select_snapshot(source, dataset):
    """Reset on every snapshot change, including changes made in analytics/quality."""
    if reset_dependency(
        "explorer_dataset_dep",
        (source, dataset),
        (
            "explorer_day",
            "explorer_route",
            "explorer_variant",
            "explorer_trip",
            "explorer_stop",
            "explorer_marker_selection",
            "explorer_marker_revision",
        ),
    ):
        st.session_state["explorer_mode"] = "Wszystkie"
        st.session_state["explorer_search"] = ""
        st.session_state["explorer_detail"] = "Kurs"
        st.session_state["explorer_vehicles"] = False


def remember_day(widget_key):
    st.session_state["explorer_day"] = st.session_state[widget_key]


def remember_detail(widget_key):
    st.session_state["explorer_detail"] = st.session_state[widget_key]


@st.cache_data(ttl=60, max_entries=128, show_spinner=False)
def fetch(source, kind, dataset, day=None, route=None, variant=None, trip=None, stop=None):
    return data.fetch(kind, dataset, day, route, variant, trip, stop)


@st.cache_data(ttl=60, max_entries=32, show_spinner=False)
def metadata(source, dataset):
    return data.metadata(dataset)


def refresh():
    fetch.clear()
    metadata.clear()


def transport(route_type):
    if route_type in (0, 900, 901, 902, 903, 904, 905, 906, 907):
        return "Tramwaj"
    if route_type == 3 or 700 <= route_type <= 716 or route_type == 800:
        return "Autobus"
    return "Inny transport"


def route_labels(records):
    names = {}
    for row in records:
        main = row["route_short_name"] or row["route_long_name"] or "Bez oznaczenia"
        names.setdefault(main, []).append(row["route_id"])
    return {
        row["route_id"]: (
            f"{row['route_short_name'] or row['route_long_name'] or 'Bez oznaczenia'} · {transport(row['route_type'])}"
            + (
                f" · {row['agency_name']} · agency_id={row['agency_id']} · route_id={row['route_id']}"
                if len(names[row["route_short_name"] or row["route_long_name"] or "Bez oznaczenia"])
                > 1
                else ""
            )
        )
        for row in records
    }


def reset_dependency(name, value, keys):
    if st.session_state.get(name) != value:
        for key in keys:
            st.session_state.pop(key, None)
        st.session_state[name] = value
        return True
    return False


def ensure_choice(key, options, default=None):
    # Explicit state writes tell the frontend to discard a selection from the old context.
    if key not in st.session_state or (
        st.session_state[key] is not None and st.session_state[key] not in options
    ):
        st.session_state[key] = default if default is not None else next(iter(options))


def select_marker(map_key, allowed):
    selection = st.session_state.get(map_key, {}).get("selection", {}).get("objects", {})
    selected = selection.get("stops", [])
    if not selected:
        st.session_state["explorer_marker_selection"] = None
        return
    stop = selected[0].get("stop_id")
    if stop not in allowed:
        return
    # Pydeck can send the same selected object again when its color/radius
    # changes. That presentation update must not override a later tab choice.
    selection = (map_key, stop)
    if st.session_state.get("explorer_marker_selection") == selection:
        return
    st.session_state["explorer_marker_selection"] = selection
    st.session_state["explorer_marker_revision"] = (
        st.session_state.get("explorer_marker_revision", 0) + 1
    )
    st.session_state["explorer_stop"] = stop
    st.session_state["explorer_detail"] = "Przystanek"


def timetable(records):
    return [
        {
            "Kolejność": r["stop_sequence"],
            "Przystanek": r.get("stop_name", ""),
            "stop_id": r.get("stop_id", ""),
            "Przyjazd": service_time(r["arrival_seconds"]),
            "Odjazd": service_time(r["departure_seconds"]),
            "Wsiadanie": {
                0: "Regularne",
                1: "Bez wsiadania",
                2: "Na żądanie telefoniczne",
                3: "Na żądanie",
            }[r["pickup_type"]],
            "Czas": "Dokładny" if r["timepoint"] else "Przybliżony",
        }
        for r in records
    ]


def vehicle_status(result):
    st.subheader("Pozycje pojazdów — osobne źródło")
    st.markdown(f"[Eksport CUI]({positions.SOURCE_URL}) · [Metadane]({positions.METADATA_URL})")
    if result["status"] == "unavailable":
        st.warning("Źródło pozycji niedostępne. Rozkład i przystanki działają niezależnie.")
        return
    st.write("Pobranie UTC:", str(result["fetched_at"]))
    st.caption(
        f"Następna próba pobrania najwcześniej: {result['next_fetch_at']} UTC. Cache wspólny dla sesji, minimum 60 minut; odświeżenie nie omija limitu."
    )
    if not result["terms_confirmed"]:
        st.warning(
            "Warunki źródła niepotwierdzone: metadane eksportu nie zgadzają się z metadanymi pozycji lub brak licencji. Integracja live pozostaje zablokowana."
        )
    if result["unconfirmed_time"]:
        st.warning(
            "Data_Aktualizacji nie zawiera potwierdzonej strefy czasowej. Wiek tych obserwacji jest nieustalony; szare punkty nie oznaczają pozycji live."
        )
    st.write(
        f"Otrzymane rekordy: {result['received']} · pominięte współrzędne/rekordy: {result['skipped']} · niepotwierdzony czas: {result['unconfirmed_time']}."
    )
    if result["duplicate_ids"]:
        st.caption(
            "Nr_Boczny nie jest unikalnym kluczem. Powtórzone identyfikatory zachowano jako osobne obserwacje."
        )
    st.caption("Numer linii nie wiąże pojazdu z trip_id. Kierunek i opóźnienie nie są wyznaczane.")


def render(source, dataset):
    st.header("Mapa i kursy", anchor=False)
    info = metadata(source, dataset)
    if not info["capabilities"].get("quantitative_gold_supported", False):
        st.warning(
            "Ten snapshot zawiera nieobsługiwane usługi częstotliwościowe/flex. Nie pokazujemy ich jako kompletnych kursów rozkładowych."
        )
        return
    all_routes = fetch(source, "routes", dataset)
    if not all_routes or not info["start_date"]:
        st.info("Brak katalogu linii lub kalendarza.")
        return
    with st.container(key="explorer_layout"):
        controls, canvas = st.columns([1, 3], gap="medium")
    with controls:
        controls_content = st.container(border=True, key="explorer_controls")
    with controls_content:
        st.subheader("Wybierz przejazd", anchor=False)
        select_snapshot(source, dataset)
        # A historical snapshot starts at its first recorded day, independently of today.
        # Later user choices, including valid days without service, remain untouched.
        initial = info["start_date"]
        if "explorer_day" not in st.session_state:
            st.session_state["explorer_day"] = initial
        # An empty default permits actual browser clearing. Scope the widget identity
        # to this snapshot so its frontend cannot reuse another snapshot's date.
        # The canonical value survives navigation when Streamlit cleans up this widget.
        day_key = (
            "explorer_day_" + hashlib.sha256(repr((source, dataset)).encode()).hexdigest()[:16]
        )
        saved_day = st.session_state["explorer_day"]
        if day_key not in st.session_state or st.session_state[day_key] != saved_day:
            st.session_state[day_key] = saved_day
        day = st.date_input(
            "Dzień usługi",
            value=None,
            key=day_key,
            format="YYYY-MM-DD",
            on_change=remember_day,
            args=(day_key,),
        )
        mode = st.selectbox(
            "Rodzaj transportu",
            ["Wszystkie", "Tramwaj", "Autobus", "Inny transport"],
            key="explorer_mode",
        )
        search = st.text_input("Szukaj linii", key="explorer_search", placeholder="Numer lub nazwa")
        if day is None:
            st.info("Wybierz dzień usługi, aby wyświetlić kursy i mapę.")
            return
        if not info["start_date"] <= day <= info["end_date"]:
            st.info(
                f"Wybrany dzień {day} jest poza zakresem snapshotu: {info['start_date']} — {info['end_date']}. Wybierz dzień z tego zakresu."
            )
            return
        labels = route_labels(all_routes)
        routes = {
            r["route_id"]: r
            for r in all_routes
            if (mode == "Wszystkie" or transport(r["route_type"]) == mode)
            and search.casefold() in (labels[r["route_id"]] + " " + r["route_long_name"]).casefold()
        }
        if not routes:
            st.info(
                "Brak linii pasujących do wyszukiwania. Wyczyść wyszukiwanie lub wybierz Wszystkie rodzaje transportu."
            )
            return
        reset_dependency(
            "explorer_routes_dep", (source, dataset, mode, search), ("explorer_route",)
        )
        active_routes = {r["route_id"] for r in fetch(source, "active_routes", dataset, day)}
        default_route = next((r for r in routes if r in active_routes), next(iter(routes)))
        ensure_choice("explorer_route", routes, default_route)
        route = st.selectbox(
            "Linia",
            list(routes),
            index=None,
            format_func=labels.__getitem__,
            key="explorer_route",
        )
        if route is None:
            st.info("Wybierz linię, aby wyświetlić jej kursy.")
            return
        selected_route = routes[route]
        variants = fetch(source, "variants", dataset, day, route)
        reset_dependency(
            "explorer_variant_dep",
            (source, dataset, day, route),
            ("explorer_variant", "explorer_trip", "explorer_stop"),
        )
        if not variants:
            with canvas:
                st.info(
                    "Brak kursów tej linii w wybranym dniu. Uwzględniono calendar i calendar_dates."
                )
                st.caption("Zmień dzień lub linię. Brak kursów nie oznacza awarii bazy.")
            return
        variant_names = {
            r["variant_key"]: (
                f"{r['trip_headsign'] or 'Brak opisu kierunku'} · kierunek {r['direction_id'] if r['direction_id'] is not None else 'niepodany'}"
                f" · wariant {r['source_variant_id'] or r['shape_id'] or r['variant_key'][:6]} · {r['trip_count']} kursów"
            )
            for r in variants
        }
        ensure_choice("explorer_variant", variant_names)
        variant = st.selectbox(
            "Kierunek / wariant",
            list(variant_names),
            index=None,
            format_func=variant_names.__getitem__,
            key="explorer_variant",
        )
        if variant is None:
            st.info("Wybierz kierunek / wariant, aby wyświetlić kursy.")
            return
        trips = fetch(source, "trips", dataset, day, route, variant)
        reset_dependency(
            "explorer_trip_dep",
            (source, dataset, day, route, variant),
            ("explorer_trip", "explorer_stop"),
        )
        by_trip = {r["trip_id"]: r for r in trips}
        if not by_trip:
            st.info("Brak kursów tego wariantu.")
            return
        ensure_choice("explorer_trip", by_trip)
        trip = st.selectbox(
            "Konkretny kurs",
            list(by_trip),
            index=None,
            key="explorer_trip",
            format_func=lambda t: (
                f"{service_time(by_trip[t]['start_seconds'])} → {service_time(by_trip[t]['end_seconds'])} · {by_trip[t]['trip_headsign'] or 'Bez opisu'} · trip_id={t}"
            ),
        )
        if trip is None:
            st.info("Wybierz konkretny kurs, aby wyświetlić mapę i rozkład.")
            return
        visits = fetch(source, "stops", dataset, day, route, variant, trip)
        names = {r["stop_id"]: r["stop_name"] for r in visits}
        reset_dependency(
            "explorer_stop_dep", (source, dataset, day, route, variant, trip), ("explorer_stop",)
        )
        if not names:
            st.info("Kurs nie ma punktów zatrzymania.")
            return
        ensure_choice("explorer_stop", names)
        stop = st.selectbox(
            "Przystanek",
            list(names),
            index=None,
            format_func=lambda s: f"{names[s]} · stop_id={s}",
            key="explorer_stop",
        )
        if stop is None:
            st.info("Wybierz przystanek, aby wyświetlić mapę i odjazdy.")
            return
        basemap = st.toggle("Podkład OpenStreetMap", value=True, key="explorer_basemap")
        with st.expander("Eksperymentalne źródło CUI"):
            show_vehicles = st.toggle("Obserwacje pojazdów z CUI", key="explorer_vehicles")
            st.caption("Osobny eksport o niepotwierdzonym czasie. To nie jest live GPS.")
            if show_vehicles:
                st.button(
                    "Odśwież pozycje", key="positions_refresh", help="Jedna próba na godzinę."
                )
    geometry = fetch(source, "geometry", dataset, day, route, variant, trip)
    observations = positions.normalize(positions.snapshot()) if show_vehicles else None
    vehicles = []
    with canvas:
        canvas_content = st.container(key="explorer_canvas")
    with canvas_content:
        chosen = by_trip[trip]
        route_card(
            selected_route,
            chosen["trip_headsign"],
            transport(selected_route["route_type"]),
            (chosen["start_seconds"], chosen["end_seconds"], len(visits)),
        )
        st.caption(
            f"Linia {selected_route['route_short_name']} → {chosen['trip_headsign'] or 'Brak opisu kierunku'} · {day}"
        )
        if observations is not None:
            st.warning(
                "Obserwacje CUI pochodzą z osobnego eksportu, nie z wybranego dnia i snapshotu GTFS. Nie identyfikują wybranego kursu; aktualność niepotwierdzona."
            )
            if info["data_kind"] == "real_gtfs":
                vehicles = [
                    p
                    for p in observations["positions"]
                    if p["line"] == selected_route["route_short_name"]
                ]
        map_key = (
            "explorer_map_"
            + hashlib.sha256(
                # Switching the basemap style must recreate the frontend map;
                # reusing its instance can leave the previous raster behind.
                repr((source, dataset, day, route, variant, trip, basemap)).encode()
            ).hexdigest()[:16]
        )
        try:
            map_event = st.pydeck_chart(
                deck(visits, geometry, stop, basemap, vehicles),
                height=445,
                key=map_key,
                on_select=lambda: select_marker(map_key, names),
                selection_mode="single-object",
            )
            if not map_event.get("selection", {}).get("objects", {}).get("stops"):
                # An omitted/recreated chart has no frontend pick. A later click
                # on the same stop is a new selection even after clearing a date.
                st.session_state["explorer_marker_selection"] = None
        except Exception:
            st.warning(
                "Mapa jest niedostępna. Wybierz przystanek z listy; rozkład i tabele pozostają dostępne."
            )
        st.caption(
            "Kliknij punkt, aby zobaczyć odjazdy. Turkus: kurs · pomarańczowy: wybrany punkt. Mapa rozkładu, bez pozycji GPS."
        )
        if basemap:
            st.markdown(
                "© [OpenStreetMap contributors](https://www.openstreetmap.org/copyright) · [Warunki kafelków](https://operations.osmfoundation.org/policies/tiles/). Podkład wymaga sieci; można go wyłączyć."
            )
        if geometry:
            st.caption(
                f"Geometria shapes właściwego kursu · shape_id={by_trip[trip]['shape_id']} · {len(geometry)} punktów · hash snapshotu: {info['source_sha256'][:12]}."
            )
        else:
            st.info(
                "Brak zaimportowanej geometrii shapes dla tego kursu. Pokazujemy przystanki, bez udawania przebiegu ulic lub torowiska."
            )
        if not show_vehicles and st.session_state.get("explorer_detail") == "Pojazdy":
            st.session_state["explorer_detail"] = "Kurs"
        # A map callback changes the canonical detail selection. Give that
        # programmatic transition a fresh native widget identity so its client
        # selection and the visible heading remain synchronized.
        detail_key = (
            "explorer_detail_"
            + hashlib.sha256(
                repr(
                    (map_key, st.session_state.get("explorer_marker_revision", 0), show_vehicles)
                ).encode()
            ).hexdigest()[:16]
        )
        saved_detail = st.session_state.get("explorer_detail", "Kurs")
        if detail_key not in st.session_state or st.session_state[detail_key] != saved_detail:
            st.session_state[detail_key] = saved_detail
        detail = st.segmented_control(
            "Szczegóły",
            ["Kurs", "Przystanek"] + (["Pojazdy"] if show_vehicles else []),
            key=detail_key,
            required=True,
            label_visibility="collapsed",
            on_change=remember_detail,
            args=(detail_key,),
        )
        if detail == "Kurs":
            st.subheader("Rozkład konkretnego kursu")
            st.text(
                f"Początek: {service_time(chosen['start_seconds'])} · koniec: {service_time(chosen['end_seconds'])}"
            )
            st.text(
                f"Kolejność: {visits[0]['stop_name']} → {visits[-1]['stop_name']} · {len(visits)} wizyt."
            )
            with st.expander("Identyfikatory kursu i geometria"):
                st.caption(
                    f"trip_id={trip} · service_id={chosen['service_id']} · direction_id={chosen['direction_id']} · wariant={chosen['source_variant_id'] or variant[:6]}"
                )
            if chosen.get("scheduled_vehicle_type_id") or chosen.get("scheduled_brigade_id"):
                st.caption(
                    f"Oznaczenia rozkładowe: vehicle_id={chosen['scheduled_vehicle_type_id']} · brigade_id={chosen['scheduled_brigade_id']}. Nie są pomiarem GPS ani potwierdzeniem konkretnego pojazdu."
                )
            with st.container(height=380, border=True):
                visit_list(visits, stop)
            with st.expander("Pełna tabela rozkładu"):
                st.dataframe(pd.DataFrame(timetable(visits)), hide_index=True, height=350)
            st.caption(
                "Każdy wiersz to wizyta według stop_sequence; powtórne wizyty zachowano. Czasy >24:00 należą do wybranego dnia usługi, brak czasu pozostaje brakiem."
            )
        elif detail == "Przystanek":
            st.subheader("Odjazdy z wybranego przystanku")
            st.text(f"{names[stop]} · stop_id={stop}")
            departures = fetch(source, "departures", dataset, day, route, variant, trip, stop)
            first_known = next(
                (r["departure_seconds"] for r in departures if r["departure_seconds"] is not None),
                None,
            )
            st.text(f"Odjazdy: {len(departures)} · pierwszy znany: {service_time(first_known)}")
            formatted = [
                {
                    "Odjazd": service_time(r["departure_seconds"]),
                    "Przyjazd": service_time(r["arrival_seconds"]),
                    "Kierunek": r["trip_headsign"] or "Niepodany",
                    "trip_id": r["trip_id"],
                    "Wizyta": r["stop_sequence"],
                    "Wsiadanie": timetable([r])[0]["Wsiadanie"],
                    "Czas": timetable([r])[0]["Czas"],
                }
                for r in departures
            ]
            st.dataframe(pd.DataFrame(formatted), hide_index=True, height=350)
            st.caption(
                "Wybrana linia, wszystkie jej aktywne warianty w tym dniu. Brak wsiadania i odjazdy na żądanie są oznaczone; nie są regularnymi odjazdami KPI."
            )
        else:
            if observations is None:
                st.info(
                    "Włącz „Obserwacje pojazdów z CUI”, aby sprawdzić osobny eksport. Pobranie następuje tylko na żądanie."
                )
            else:
                vehicle_status(observations)
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "Linia": p["line"],
                                "Nr_Boczny": p["vehicle_id"],
                                "Powtórzony numer": p["duplicate_id"],
                                "Czas źródłowy": p["measured_at"],
                                "Wiek [s]": p["age_seconds"],
                                "Status": p["state"],
                            }
                            for p in vehicles
                        ]
                    ),
                    hide_index=True,
                )
