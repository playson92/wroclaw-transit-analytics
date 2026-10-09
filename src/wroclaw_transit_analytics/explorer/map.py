"""Selectable Pydeck layers, an attributed optional OSM basemap, no invented road paths."""

import json
import math
from urllib.parse import quote

import pydeck as pdk
from pydeck.data_utils.viewport_helpers import compute_view

OSM_STYLE = {
    "version": 8,
    "sources": {
        "osm": {
            "type": "raster",
            "tiles": ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
            "tileSize": 256,
            "attribution": '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>',
        }
    },
    "layers": [{"id": "osm", "type": "raster", "source": "osm", "minzoom": 0, "maxzoom": 19}],
}


def stop_markers(visits, selected):
    markers = {}
    for visit in visits:
        lat, lon = visit["stop_lat"], visit["stop_lon"]
        if lat is None or lon is None or not math.isfinite(lat) or not math.isfinite(lon):
            continue
        key = visit["stop_id"]
        markers[key] = {
            "stop_id": key,
            "latitude": lat,
            "longitude": lon,
            "label": f"{visit['stop_name']}\nstop_id={key}",
            "color": [245, 158, 11] if key == selected else [15, 118, 110],
            "radius": 9 if key == selected else 6,
        }
    return list(markers.values())


def deck(visits, geometry, selected, basemap=True, vehicles=()):
    markers = stop_markers(visits, selected)
    layers = []
    if geometry:
        layers.append(
            pdk.Layer(
                "PathLayer",
                id="trip-shape",
                data=[
                    {
                        "path": [[r["longitude"], r["latitude"]] for r in geometry],
                    }
                ],
                get_path="path",
                get_color=[15, 118, 110],
                width_min_pixels=4,
                pickable=False,
            )
        )
    layers.append(
        pdk.Layer(
            "ScatterplotLayer",
            id="stops",
            data=markers,
            get_position="[longitude,latitude]",
            get_fill_color="color",
            get_radius="radius",
            radius_units="pixels",
            pickable=True,
            auto_highlight=True,
            stroked=True,
            get_line_color=[255, 255, 255],
            line_width_min_pixels=2,
        )
    )
    if vehicles:
        layers.append(
            pdk.Layer(
                "ScatterplotLayer",
                id="vehicles",
                data=list(vehicles),
                get_position="[longitude,latitude]",
                get_radius=7,
                radius_units="pixels",
                get_fill_color=[100, 116, 139],
                pickable=True,
                auto_highlight=True,
            )
        )
    points = [[r["longitude"], r["latitude"]] for r in geometry or markers]
    if not points:
        points = [[r["longitude"], r["latitude"]] for r in vehicles]
    view = (
        compute_view(points, view_proportion=0.82)
        if len(points) > 1
        else pdk.ViewState(
            longitude=points[0][0] if points else 17.04,
            latitude=points[0][1] if points else 51.11,
            zoom=13,
        )
    )
    view.zoom = min(view.zoom, 16)
    return pdk.Deck(
        layers=layers,
        initial_view_state=view,
        map_provider="mapbox" if basemap else None,
        # Streamlit 1.57 expects a style URL string, although Pydeck accepts a dict.
        map_style="data:application/json," + quote(json.dumps(OSM_STYLE)) if basemap else None,
        tooltip={"text": "{label}"},
    )
