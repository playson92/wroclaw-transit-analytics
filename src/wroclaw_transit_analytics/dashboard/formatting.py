"""Presentation only; no reconstruction of service calendars or KPI."""

SYNTHETIC_NOTICE = "DANE SYNTETYCZNE — nie rozkład Wrocławia"


def notice(kind):
    if kind in ("synthetic_demo", "synthetic_benchmark"):
        return SYNTHETIC_NOTICE
    return "Oficjalny GTFS Wrocławia" if kind == "real_gtfs" else "Niepotwierdzony rodzaj danych"


def number(value):
    return "Brak danych" if value is None else f"{int(value):,}".replace(",", " ")


def service_time(seconds):
    if seconds is None:
        return "Brak czasu"
    hours, tail = divmod(int(seconds), 3600)
    minutes, seconds = divmod(tail, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def percent(numerator, denominator):
    if numerator is None or denominator is None or denominator == 0:
        return "Nieokreślone"
    return f"{100 * numerator / denominator:.1f}%"


def direction_label(value):
    return {"ALL": "Wszystkie kierunki", "NULL": "Niepodany", "0": "0", "1": "1"}[value]
