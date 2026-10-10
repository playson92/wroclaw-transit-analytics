"""Polish UI with one explicit snapshot/analysis and dependent filters."""

from dataclasses import replace

import altair as alt
import pandas as pd
import streamlit as st

from . import cache, data
from .formatting import direction_label, notice, number, percent, service_time

VIEWS = ("Mapa i linie", "Analityka", "Dane i jakość")
ANALYTICS_VIEWS = ("Przegląd sieci", "Linia / punkt zatrzymania")


def dataset_labels(datasets):
    """Use recorded provenance, never infer an up-to-date timetable from an import."""
    labels = {}
    for dataset, row in datasets.items():
        provenance = row.get("provenance") or {}
        if row.get("data_kind") == "real_gtfs":
            stamp = provenance.get("downloaded_at")
            label = "Snapshot GTFS Wrocławia"
            label += (
                f" · pobrano {str(stamp)[:19].replace('T', ' ')} UTC"
                if stamp
                else " · data pobrania niepodana"
            )
        elif row.get("data_kind") == "synthetic_demo":
            stamp = provenance.get("generated_at")
            label = "Demo syntetyczne"
            label += (
                f" · wygenerowano {str(stamp)[:19].replace('T', ' ')} UTC"
                if stamp
                else " · data generowania niepodana"
            )
        else:
            label = "Snapshot o niepotwierdzonym pochodzeniu"
        labels[dataset] = label
    for label in set(labels.values()):
        duplicates = [dataset for dataset, name in labels.items() if name == label]
        if len(duplicates) > 1:
            for i, dataset in enumerate(duplicates, start=1):
                labels[dataset] += f" · snapshot {i}"
    return labels


def table(records, labels=None):
    st.dataframe(pd.DataFrame(records, dtype=object).rename(columns=labels or {}), hide_index=True)


def hourly(records):
    st.subheader("Profil godzinowy regularnych znanych odjazdów")
    if not records:
        st.info("Brak znanych regularnych odjazdów. Sprawdź pokrycie i braki czasów.")
        return
    if len(records) > 200:
        st.info("Wykres pokazuje 200 godzin z największą liczbą odjazdów. KPI obejmują cały filtr.")
        records = sorted(
            sorted(records, key=lambda r: r["departures"], reverse=True)[:200],
            key=lambda r: r["service_hour"],
        )
    frame = pd.DataFrame(records)
    frame["Godzina usługowa"] = frame["service_hour"].map(lambda h: f"{h}:00")
    # Ordinal, observed categories only: even hour 1000000 cannot expand an empty axis.
    chart = (
        alt.Chart(frame)
        .mark_bar(color="#0f766e")
        .encode(
            x=alt.X(
                "Godzina usługowa:N",
                sort=frame["Godzina usługowa"].tolist(),
                axis=alt.Axis(labelAngle=-35),
            ),
            y=alt.Y("departures:Q", title="Odjazdy [liczba]"),
            tooltip=["Godzina usługowa:N", alt.Tooltip("departures:Q", title="Odjazdy")],
        )
    )
    st.altair_chart(chart, height=280)


def overview(result):
    st.header("Przegląd sieci")
    k = result["kpi"]
    with st.container(horizontal=True):
        for label, key in (
            ("Instancje kursów", "trips"),
            ("Znane regularne odjazdy", "departures"),
            ("Aktywne linie", "active_routes"),
            ("Obsługiwane punkty", "served_stops"),
        ):
            st.metric(label, number(k[key]), border=True)
    st.caption(
        "Kurs = trip_id w dniu usługi. Odjazd = wizyta z pickup_type=0 i znanym czasem. "
        "Obsługiwany punkt = stop_id odwiedzony przez aktywny kurs, także bez regularnego czasu."
    )
    if k["covered_days"] != k["requested_days"]:
        st.warning(
            "Niepełny zakres kalendarza: wyniki obejmują tylko pokryte dni; pozostałe są nieznane."
        )
    st.write(
        f"Dni w obwiedni kalendarza: {k['covered_days']} / {k['requested_days']}. "
        f"Znane czasy regularnych odjazdów: {percent(k['departures'], k['regular_events'])}."
    )
    st.caption(
        f"Katalog zawiera {number(k['catalog_stops'])} punktów wszystkich typów; "
        "liczba w katalogu nie jest liczbą obsługiwanych platform."
    )
    hourly(result["hourly"])
    left, right = st.columns(2)
    with left:
        st.subheader("Linie — ranking instancji kursów")
        table(
            result["routes"],
            {"route_id": "route_id", "route_short_name": "Linia", "trips": "Kursy"},
        )
    with right:
        st.subheader("Punkty — ranking regularnych znanych odjazdów")
        table(result["stops"], {"stop_name": "Nazwa", "departures": "Odjazdy"})
    st.caption("Top 20 w tabelach; KPI powyżej obejmują całą populację wybranego okresu.")
    with st.expander("Pokrycie gold dzień po dniu"):
        coverage_table(result["coverage"])


def coverage_table(records):
    labels = {
        "service_date": "Dzień",
        "calendar_covered": "W obwiedni",
        "total_events": "Wizyty stop_times",
        "known_arrivals": "Znane przyjazdy",
        "missing_arrivals": "Brakujące przyjazdy",
        "known_departures": "Wszystkie znane odjazdy",
        "missing_departures": "Wszystkie braki odjazdów",
        "regular_events": "Regularne wizyty — mianownik",
        "regular_known_departures": "Znane regularne odjazdy",
        "regular_missing_departures": "Regularne braki czasów",
        "no_pickup_events": "Bez wsiadania",
        "on_request_events": "Na żądanie",
        "approximate_regular_departures": "Przybliżone znane regularne",
        "known_regular_departure_ratio": "Udział znanych regularnych [0–1]",
    }
    table([{key: r.get(key) for key in labels} for r in records], labels)


def group(source, context):
    st.header("Linia / punkt zatrzymania")
    available = cache.fetch(source, "filters", context)
    routes = {r["route_id"]: r for r in available["routes"]}
    if not routes:
        st.info("Brak katalogu linii.")
        return
    route = st.selectbox(
        "Linia",
        list(routes),
        key="filter_route",
        format_func=lambda r: f"{routes[r]['route_short_name']} · route_id={r}",
    )
    if route is None:
        st.info("Wybierz linię, aby wyświetlić analizę jej odjazdów.")
        return
    route_context = replace(context, route=route)
    stops = cache.fetch(source, "filters", route_context)["stops"]
    names = {r["stop_id"]: r["stop_name"] for r in stops}
    if not names:
        st.info("Brak wizyt punktów dla tej linii w wybranym okresie. Sprawdź zakres kalendarza.")
        return
    dependency = (context.dataset, context.analysis, context.start, context.end, route)
    if st.session_state.get("stop_dependency") != dependency:
        st.session_state.pop("filter_stop", None)
        st.session_state.pop("filter_direction", None)
        st.session_state["stop_dependency"] = dependency
    stop = st.selectbox(
        "Punkt zatrzymania",
        list(names),
        key="filter_stop",
        format_func=lambda s: f"{names[s]} · stop_id={s}",
    )
    if stop is None:
        st.info("Wybierz punkt zatrzymania, aby wyświetlić analizę odjazdów.")
        return
    stop_context = replace(route_context, stop=stop)
    directions = cache.fetch(source, "filters", stop_context)["directions"]
    options = ["ALL"] + [
        "NULL" if r["direction_id"] is None else str(r["direction_id"]) for r in directions
    ]
    if st.session_state.get("direction_dependency") != (dependency, stop):
        st.session_state.pop("filter_direction", None)
        st.session_state["direction_dependency"] = (dependency, stop)
    direction = st.selectbox(
        "Źródłowy direction_id", options, format_func=direction_label, key="filter_direction"
    )
    if direction is None:
        st.info("Wybierz kierunek lub Wszystkie, aby wyświetlić analizę odjazdów.")
        return
    result = cache.fetch(source, "group", replace(stop_context, direction=direction))
    st.caption(
        "Wyniki dotyczą wybranego route_id, stop_id i kierunku. Każda mediana/p90 "
        "opisuje jeden dzień i kierunek; nie wyliczamy mediany całego okresu."
    )
    daily = [
        {
            **r,
            "Pierwszy znany czas": service_time(r["first_seconds"]),
            "Ostatni znany czas": service_time(r["last_seconds"]),
            "Pokrycie grupy": percent(r["departures"], r["regular_events"]),
        }
        for r in result["daily"]
    ]
    st.subheader("Dzienne odjazdy i pokrycie wybranej grupy")
    if daily:
        st.text("Pierwszy znany czas (pierwszy dzień): " + daily[0]["Pierwszy znany czas"])
    table(
        [{k: v for k, v in r.items() if k not in ("first_seconds", "last_seconds")} for r in daily],
        {
            "service_date": "Dzień",
            "calendar_covered": "W obwiedni",
            "departures": "Odjazdy",
            "regular_events": "Regularne wizyty",
            "missing": "Brakujące czasy",
            "approximate": "Przybliżone znane",
        },
    )
    hourly(result["hourly"])
    st.subheader("Odstępy — statystyki dzienne [sekundy]")
    headways = [
        {**r, "direction_id": "Niepodany" if r["direction_id"] is None else str(r["direction_id"])}
        for r in result["headways"]
    ]
    table(
        headways,
        {
            "service_date": "Dzień",
            "direction_id": "Kierunek",
            "departure_count": "Obserwacje",
            "interval_count": "Odstępy",
            "avg_seconds": "Średnia [s]",
            "median_seconds": "Mediana [s]",
            "p90_seconds": "p90 [s]",
        },
    )
    st.caption(
        "Jedna obserwacja daje 0 odstępów i nieokreślone statystyki. Znany pierwszy/ostatni "
        "czas przy brakach nie gwarantuje pełnego span. Kursy całej linii nie są KPI tego filtra."
    )


def quality(result):
    st.header("Dane i jakość")
    dataset, analysis = result["dataset"], result["analysis"]
    provenance = dataset.get("provenance") or {}
    st.write("Rodzaj danych:", dataset.get("data_kind", "Niepotwierdzony"))
    source = provenance.get("final_url") or provenance.get("requested_url")
    st.text("Źródło: " + (source or "Lokalny generator; brak adresu pobrania"))
    st.write("Pobranie UTC:", provenance.get("downloaded_at") or "Nie dotyczy / brak metadanych")
    st.write("Generowanie UTC:", provenance.get("generated_at") or "Nie dotyczy / brak metadanych")
    st.write("Import UTC:", str(dataset["loaded_at"]))
    st.write("Analiza UTC:", str(analysis["created_at"]))
    st.write("Model:", dataset["model_version"], "· KPI:", analysis["metrics_version"])
    st.write(
        "Zakres analizy:",
        f"{analysis['start_date']} — {analysis['end_date']} (obie granice włącznie)",
    )
    st.info(
        "wta-gold-v1 nie rozwija frequencies. Flex nie jest obsługiwany przez profil silver. "
        "Obwiednia kalendarza nie gwarantuje aktywnej usługi każdego dnia. Czasy zachowują dzień "
        "usługowy, bez przeliczania na UTC ani interpretacji DST jako zegara ściennego."
    )
    with st.expander("Identyfikatory i hash", expanded=True):
        for key, value in (
            ("dataset_id", dataset["dataset_id"]),
            ("analysis_id", analysis["analysis_id"]),
            ("SHA-256 źródła", dataset["source_sha256"]),
            ("Fingerprint", dataset["logical_fingerprint"]),
        ):
            st.text(f"{key}: {value}")
    with st.expander("Jakość silver — statyczne rekordy źródła"):
        st.json(dataset["quality_report"])
        st.json(dataset["capabilities"])
    with st.expander("Pokrycie gold — aktywne zdarzenia w filtrze dat", expanded=True):
        st.caption(
            "total_events to wizyty stop_times, regular_events to mianownik znanych "
            "regularnych odjazdów. no_pickup i on_request są wykluczone. NULL oznacza "
            "nieznane; mianownik 0 nie daje procentu pokrycia."
        )
        coverage_table(result["coverage"])


def main():
    st.set_page_config(
        page_title="Wrocław Transit Analytics", page_icon=":material/tram:", layout="wide"
    )
    st.title("Wrocław Transit Analytics")
    st.caption("Przeglądarka komunikacji · rozkład zapisany w GTFS · analityka SQL gold")
    try:
        source = data.source_key()
        if st.sidebar.button("Odśwież dane", icon=":material/refresh:"):
            cache.refresh()
            from ..explorer import ui as explorer_ui

            explorer_ui.refresh()
        catalog = cache.catalog(source)
        datasets = {r["dataset_id"]: r for r in catalog["datasets"]}
        if not datasets:
            st.info("Brak zaimportowanych datasetów. Uruchom demo lub pipeline run.")
            return
        labels = dataset_labels(datasets)
        if "dataset" not in st.session_state or (
            st.session_state["dataset"] is not None and st.session_state["dataset"] not in datasets
        ):
            st.session_state["dataset"] = next(iter(datasets))
        dataset = st.sidebar.selectbox(
            "Snapshot danych",
            list(datasets),
            index=None,
            key="dataset",
            format_func=labels.__getitem__,
        )
        if dataset is None:
            st.info("Wybierz snapshot danych, aby otworzyć mapę i analitykę.")
            return
        from ..explorer import ui as explorer_ui

        explorer_ui.select_snapshot(source, dataset)
        with st.sidebar.expander("Identyfikator snapshotu"):
            st.text(f"Wybrany dataset_id: {dataset}")
        analyses = {r["analysis_id"]: r for r in catalog["analyses"] if r["dataset_id"] == dataset}
        st.warning(notice(datasets[dataset].get("data_kind"))) if datasets[dataset].get(
            "data_kind"
        ) != "real_gtfs" else st.caption(notice("real_gtfs"))
        view = st.sidebar.radio("Widok", VIEWS, key="view")
        # Widget cleanup runs even though these are radio views within one Streamlit page.
        # Keep selections for this snapshot while visiting analytics/quality.
        explorer_ui.retain_filters()
        if view == "Mapa i linie":
            explorer_ui.render(source, dataset)
            return
        if not analyses:
            st.info("Brak kompletnej analizy gold dla tego snapshotu. To nie są zerowe wyniki.")
            return
        if st.session_state.get("analysis_dependency") != (source, dataset):
            st.session_state.pop("analysis", None)
            st.session_state["analysis_dependency"] = (source, dataset)
        if "analysis" not in st.session_state or (
            st.session_state["analysis"] is not None
            and st.session_state["analysis"] not in analyses
        ):
            st.session_state["analysis"] = next(iter(analyses))
        analysis = st.sidebar.selectbox(
            "Analiza",
            list(analyses),
            index=None,
            key="analysis",
            format_func=lambda a: (
                f"{analyses[a]['start_date']} — {analyses[a]['end_date']} · {a[-10:]}"
            ),
        )
        if analysis is None:
            st.info("Wybierz analizę, aby wyświetlić wyniki gold.")
            return
        selected = analyses[analysis]
        if st.session_state.get("context_dependency") != (source, dataset, analysis):
            for key in ("dates", "filter_route", "filter_stop", "filter_direction"):
                st.session_state.pop(key, None)
            st.session_state["context_dependency"] = (source, dataset, analysis)
        dates = st.sidebar.date_input(
            "Zakres dni usługowych",
            value=(selected["start_date"], selected["end_date"]),
            min_value=selected["start_date"],
            max_value=selected["end_date"],
            key="dates",
            format="YYYY-MM-DD",
        )
        if not isinstance(dates, (tuple, list)) or len(dates) != 2:
            st.info("Wybierz obie granice zakresu dat.")
            return
        context = data.Context(dataset, analysis, *dates)
        if view == "Dane i jakość":
            quality(cache.fetch(source, "quality", context))
        else:
            analytical_view = st.sidebar.radio(
                "Widok analityki", ANALYTICS_VIEWS, key="analytics_view"
            )
            if analytical_view == ANALYTICS_VIEWS[0]:
                overview(cache.fetch(source, "overview", context))
            else:
                group(source, context)
    except data.DashboardError as exc:
        st.error(str(exc))
    except Exception:
        st.error("Nie udało się wyświetlić danych. Sprawdź wersję pakietu i konfigurację bazy.")
