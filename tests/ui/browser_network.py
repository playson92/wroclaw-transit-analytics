"""Keep UI acceptance on its local app and controlled synthetic tile responses."""

import re
from urllib.parse import urlsplit


def protect_local_browser(page, url, tile_handler=None):
    origin = urlsplit(url)
    local = (origin.scheme, origin.hostname, origin.port)
    unexpected = []

    def handle(route):
        target = urlsplit(route.request.url)
        if (target.scheme, target.hostname, target.port) == local:
            route.continue_()
        elif target.hostname == "tile.openstreetmap.org":
            if tile_handler is None:
                route.abort()
            else:
                tile_handler(route)
        else:
            unexpected.append(route.request.url)
            route.abort()

    # Block every external HTTP(S) provider before any request can leave CI.
    # OSM is only aborted or served by the explicit local synthetic handler.
    page.route(re.compile(r"^https?://"), handle)
    return unexpected
