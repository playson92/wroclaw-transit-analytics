"""Launch the installed app resource, independently of the current directory."""

import subprocess
import sys
from importlib.resources import as_file, files

from ..database import DatabaseError


def launch(port=8501, address="127.0.0.1"):
    try:
        import streamlit  # noqa: F401
    except ImportError:
        raise DatabaseError('Dashboard wymaga instalacji: pip install ".[dashboard]".') from None
    if not 1 <= port <= 65535:
        raise DatabaseError("Port dashboardu musi być w zakresie 1–65535.")
    with as_file(files("wroclaw_transit_analytics.dashboard").joinpath("app.py")) as path:
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                str(path),
                f"--server.port={port}",
                f"--server.address={address}",
                "--server.headless=true",
                "--browser.gatherUsageStats=false",
                "--client.showErrorDetails=false",
                "--server.fileWatcherType=none",
            ]
        ).returncode
