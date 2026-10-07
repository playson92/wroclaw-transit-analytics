"""Explicit source scenarios; these generators do not calculate expected KPI."""

from tests.preparation.conftest import csv_contents

from wroclaw_transit_analytics.sample_data import sample_files

CALENDAR_COLUMNS = [
    "service_id",
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
    "start_date",
    "end_date",
]
TRIP_COLUMNS = ["route_id", "service_id", "trip_id", "direction_id"]
EVENT_COLUMNS = [
    "trip_id",
    "arrival_time",
    "departure_time",
    "stop_id",
    "stop_sequence",
    "pickup_type",
    "timepoint",
]


def numerical_files():
    files = sample_files()
    files["routes.txt"] = csv_contents(
        ["route_id", "route_short_name", "route_type"],
        [["R1", "R1", 3], ["R2", "R2", 3], ["R0", "Zero", 3]],
    )
    files["calendar.txt"] = csv_contents(
        CALENDAR_COLUMNS,
        [
            ["WD", 1, 1, 1, 1, 1, 0, 0, "20261001", "20261005"],
            ["WE", 0, 0, 0, 0, 0, 1, 1, "20261001", "20261005"],
        ],
    )
    files["calendar_dates.txt"] = csv_contents(
        ["service_id", "date", "exception_type"],
        [
            ["WD", "20261002", 1],
            ["WD", "20261005", 2],
            ["WE", "20261002", 1],
            ["EX", "20261003", 1],
        ],
    )
    files["trips.txt"] = csv_contents(
        TRIP_COLUMNS,
        [
            ["R1", "WD", "A", 0],
            ["R1", "WD", "B", 0],
            ["R1", "WD", "C", 0],
            ["R2", "WD", "D", 1],
            ["R1", "WE", "W", ""],
            ["R2", "EX", "E", ""],
        ],
    )
    events = [
        ["A", "07:50:00", "07:50:00", "0001", 0, 0, 1],
        ["A", "08:20:00", "08:20:00", "NA", 1, 1, 1],
        ["A", "08:40:00", "08:40:00", "0001", 2, 0, 1],
        ["B", "08:10:00", "08:10:00", "0001", 0, 0, 1],
        ["B", "08:40:00", "08:40:00", "NA", 1, 2, 1],
        ["B", "08:50:00", "08:50:00", "NULL", 2, 3, 1],
        ["C", "08:10:00", "08:10:00", "0001", 0, 0, 1],
        ["C", "", "", "NA", 1, 0, 0],
        ["C", "09:00:00", "09:00:00", "NULL", 2, 0, 0],
        ["D", "23:50:00", "23:50:00", "0001", 0, 0, 1],
        ["D", "25:10:00", "25:10:00", "NA", 1, 0, 1],
        ["D", "1000000:00:00", "1000000:00:00", "NULL", 2**40, 0, 1],
        ["W", "10:00:00", "10:00:00", "0001", 0, 0, 1],
        ["E", "11:00:00", "11:00:00", "NA", 0, 0, 1],
    ]
    files["stop_times.txt"] = csv_contents(EVENT_COLUMNS, events)
    return files


def benchmark_files(trips=1000, stops=20):
    files = sample_files()
    files["stops.txt"] = csv_contents(
        ["stop_id", "stop_name", "stop_lat", "stop_lon"],
        [[f"S{i}", f"Synthetic {i}", 51.1, 17.1] for i in range(stops)],
    )
    files["routes.txt"] = csv_contents(
        ["route_id", "route_short_name", "route_type"], [[f"R{i}", f"R{i}", 3] for i in range(10)]
    )
    files["calendar.txt"] = csv_contents(
        CALENDAR_COLUMNS, [["WD", 1, 1, 1, 1, 1, 1, 1, "20261001", "20261031"]]
    )
    files["calendar_dates.txt"] = csv_contents(["service_id", "date", "exception_type"], [])
    files["trips.txt"] = csv_contents(
        TRIP_COLUMNS, [[f"R{i % 10}", "WD", f"T{i:05}", i % 2] for i in range(trips)]
    )
    events = []
    for trip in range(trips):
        for stop in range(stops):
            seconds = 28800 + trip * 30 + stop * 60
            time = f"{seconds // 3600}:{seconds // 60 % 60:02}:{seconds % 60:02}"
            events.append([f"T{trip:05}", time, time, f"S{stop}", stop, 0, 1])
    files["stop_times.txt"] = csv_contents(EVENT_COLUMNS, events)
    return files
