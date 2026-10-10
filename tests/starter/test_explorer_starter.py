"""Exercise the Windows orchestrator with native commands, without touching Docker."""

import json
import os
import shutil
import socket
import subprocess
import sys
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

STARTER = Path(__file__).resolve().parents[2] / "scripts" / "start-explorer.ps1"
POWERSHELL = shutil.which("powershell.exe") if sys.platform == "win32" else None
pytestmark = pytest.mark.skipif(not POWERSHELL, reason="Windows PowerShell starter contract")

FAKE_DOCKER = r"""
import json, os, sys
from pathlib import Path

args = sys.argv[1:]
with Path(os.environ["MOCK_LOG"]).open("a", encoding="utf-8") as log:
    log.write(json.dumps({"args": args, "raw": os.environ.get("RAW_DIR"),
                          "host": os.environ.get("DOCKER_HOST"),
                          "password": bool(os.environ.get("POSTGRES_PASSWORD"))}) + "\n")
if args[:2] != ["--context", "desktop-linux"]:
    raise SystemExit(91)
args = args[2:]
failure = os.environ.get("MOCK_FAILURE")
if failure and failure in " ".join(args):
    print("password=secret_native_failure", file=sys.stderr)
    print("last useful diagnostic: mock native failure", file=sys.stderr)
    raise SystemExit(23)
if args[:2] == ["context", "inspect"]:
    print(os.environ.get("MOCK_ENDPOINT", "npipe:////./pipe/dockerDesktopLinuxEngine"))
elif args[0] == "info":
    print("linux/amd64")
elif args[:2] == ["volume", "ls"]:
    if os.environ.get("MOCK_HAS_VOLUMES") == "1":
        database_only = "label=com.docker.compose.volume=postgres_data" in args
        if not database_only or os.environ.get("MOCK_ONLY_WORK_VOLUME") != "1":
            print("owned_project_postgres_data" if database_only else "owned_project_pipeline_work")
elif args[:2] == ["compose", "version"]:
    print("5.5.1")
elif "-f" in args:
    stage = args[args.index("-f") + 2:]
    if stage[:1] == ["ps"]:
        pass
    elif "wroclaw_transit_analytics.gtfs" in stage:
        print("Walidacja passed\nManifest: /work/actual download result/manifest.json")
    elif "explorer-import" in stage:
        print(json.dumps({"status": "IMPORTED", "dataset_id": "returned_dataset",
                          "geometry_status": "absent"}))
    elif "demo" in stage or ("pipeline" in stage and stage[stage.index("pipeline") + 1:][:1] == ["run"]):
        raw = (stage[stage.index("--raw-manifest") + 1] if "--raw-manifest" in stage
               else "/work/actual generated demo/manifest.json")
        print(json.dumps({"status": "PASSED", "dataset_id": "returned_dataset",
                          "raw_manifest": raw, "analysis_id": "returned_analysis"}))
    else:
        print("ordinary native progress on stderr", file=sys.stderr)
"""


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/_stcore/health":
            self.send_error(404)
            return
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *_args):
        pass


@contextmanager
def health_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), HealthHandler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


def quote_ps(value):
    return "'" + str(value).replace("'", "''") + "'"


@pytest.fixture
def harness(tmp_path):
    root = tmp_path / "fresh checkout with spaces"
    root.mkdir()
    (root / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    native = tmp_path / "native commands"
    native.mkdir()
    mock = native / "fake_docker.py"
    mock.write_text(FAKE_DOCKER, encoding="utf-8")
    (native / "docker.cmd").write_text(
        f'@echo off\n"{sys.executable}" "{mock}" %*\n', encoding="utf-8"
    )
    log = tmp_path / "native-calls.jsonl"
    env = os.environ.copy()
    env.update(PATH=str(native) + os.pathsep + env["PATH"], MOCK_LOG=str(log))
    env["DOCKER_HOST"] = "tcp://remote-must-not-be-used:2375"
    env["POSTGRES_PASSWORD"] = "inherited-must-not-be-used"
    # A listening socket is used only for the HTTP health endpoint. The mocked Compose
    # reports its dashboard port as owned, avoiding a fake Docker bind of that endpoint.
    patch = FAKE_DOCKER.replace(
        'if stage[:1] == ["ps"]:\n        pass',
        'if stage[:1] == ["ps"]:\n        if stage[-1] == "dashboard": print("owned_dashboard")\n'
        '    elif stage[:1] == ["port"]:\n'
        '        print("127.0.0.1:" + os.environ["DASHBOARD_PORT"])',
    )
    mock.write_text(patch, encoding="utf-8")

    def run(args=(), postgres_port=None, **environment):
        child_env = env | environment
        if postgres_port is None:
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                postgres_port = probe.getsockname()[1]
        with health_server() as port:
            command = (
                "$ErrorActionPreference='Stop'; "
                "$policy=Get-ExecutionPolicy; "
                "if ($policy -eq 'Restricted' -and "
                "(Get-ExecutionPolicy -Scope MachinePolicy) -eq 'Undefined' -and "
                "(Get-ExecutionPolicy -Scope UserPolicy) -eq 'Undefined') "
                "{ Set-ExecutionPolicy RemoteSigned -Scope Process -Force }; "
                f"& {quote_ps(STARTER)} -RepoRoot {quote_ps(root)} "
                f"-ProjectName starter-test -DashboardPort {port} -PostgresPort {postgres_port} "
                + " ".join(quote_ps(arg) if not arg.startswith("-") else arg for arg in args)
                + "; if ($env:POSTGRES_PASSWORD -ne 'inherited-must-not-be-used') "
                "{ throw 'Process environment was not restored' }"
            )
            result = subprocess.run(
                [POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", command],
                env=child_env,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=45,
            )
        calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        return result, calls

    return root, run


def credentials(root):
    path = root / ".env.starter-test"
    path.write_text(
        "POSTGRES_PASSWORD=existing-admin\nWTA_LOADER_PASSWORD=existing-loader\n"
        "WTA_READER_PASSWORD=existing-reader\n",
        encoding="utf-8",
    )
    return path


def stages(calls):
    return [call["args"] for call in calls if "-f" in call["args"]]


def test_restart_preserves_configuration_and_only_builds_dashboard(harness):
    root, run = harness
    config = credentials(root)
    before = config.read_bytes()
    result, calls = run(MOCK_HAS_VOLUMES="1")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Explorer uruchomiony: http://127.0.0.1:" in result.stdout
    assert config.read_bytes() == before
    assert not any("pipeline" in args or "initializer" in args for args in stages(calls))
    assert any(args[-2:] == ["build", "dashboard"] for args in stages(calls))
    assert all(call["host"] is None and not call["password"] for call in calls)


def test_demo_passes_actual_manifest_to_geometry_and_reuses_passwords(harness):
    root, run = harness
    result, calls = run(["-Demo"])
    assert result.returncode == 0, result.stdout + result.stderr
    config = root / ".env.starter-test"
    before = config.read_bytes()
    geometry = next(args for args in stages(calls) if "explorer-import" in args)
    assert (
        geometry[geometry.index("--raw-manifest") + 1]
        == "/work/actual generated demo/manifest.json"
    )
    assert all(line.split("=", 1)[1] not in result.stdout for line in before.decode().splitlines())
    repeat, _calls = run(["-Demo"], MOCK_HAS_VOLUMES="1")
    assert repeat.returncode == 0, repeat.stdout + repeat.stderr
    assert config.read_bytes() == before


@pytest.mark.parametrize("source", ["manifest", "url"])
def test_explicit_sources_pass_actual_paths_and_dates(harness, source):
    root, run = harness
    if source == "manifest":
        manifest = root / "input with spaces" / "selected manifest.json"
        manifest.parent.mkdir()
        manifest.write_text("{}", encoding="utf-8")
        args = ["-RawManifest", str(manifest)]
        expected = "/input/raw/selected manifest.json"
    else:
        args = ["-GtfsUrl", "https://open-data.cui.wroclaw.pl/hdb/download/141/"]
        expected = "/work/actual download result/manifest.json"
    result, calls = run(args + ["-StartDate", "2026-10-01", "-EndDate", "2026-10-07"])
    assert result.returncode == 0, result.stdout + result.stderr
    flow = next(args for args in stages(calls) if "--start-date" in args)
    geometry = next(args for args in stages(calls) if "explorer-import" in args)
    assert flow[flow.index("--raw-manifest") + 1] == expected
    assert geometry[geometry.index("--raw-manifest") + 1] == expected
    assert flow[flow.index("--start-date") + 1] == "2026-10-01"
    assert flow[flow.index("--end-date") + 1] == "2026-10-07"
    if source == "manifest":
        assert any(call["raw"] == str(manifest.parent).replace("\\", "/") for call in calls)
        assert not any("wroclaw_transit_analytics.gtfs" in args for args in stages(calls))


def test_native_failure_reports_exit_code_and_redacts_credentials(harness):
    _root, run = harness
    result, _calls = run(["-Demo"], MOCK_FAILURE="pipeline demo")
    combined = result.stdout + result.stderr
    assert result.returncode != 0
    assert "(23)" in combined and "last useful diagnostic: mock native failure" in combined
    assert "secret_native_failure" not in combined
    assert "Explorer uruchomiony:" not in combined


def test_missing_configuration_with_owned_volumes_refuses_new_credentials(harness):
    root, run = harness
    result, calls = run(["-Demo"], MOCK_HAS_VOLUMES="1")
    assert result.returncode != 0
    assert not (root / ".env.starter-test").exists()
    assert not stages(calls)


def test_remote_endpoint_is_rejected_before_compose(harness):
    _root, run = harness
    result, calls = run(["-Demo"], MOCK_ENDPOINT="tcp://remote:2375")
    assert result.returncode != 0
    assert not stages(calls)


def test_restart_without_owned_volumes_does_not_initialize_database(harness):
    root, run = harness
    config = credentials(root)
    before = config.read_bytes()
    result, calls = run()
    assert result.returncode != 0
    assert config.read_bytes() == before
    assert not stages(calls)


def test_restart_with_only_pipeline_volume_does_not_create_empty_database(harness):
    root, run = harness
    config = credentials(root)
    before = config.read_bytes()
    result, calls = run(MOCK_HAS_VOLUMES="1", MOCK_ONLY_WORK_VOLUME="1")
    assert result.returncode != 0
    assert "postgres_data" in result.stdout + result.stderr
    assert config.read_bytes() == before
    assert not stages(calls)


def test_foreign_listener_is_preserved_and_blocks_build(harness):
    root, run = harness
    config = credentials(root)
    before = config.read_bytes()
    with socket.socket() as foreign:
        foreign.bind(("127.0.0.1", 0))
        foreign.listen(1)
        port = foreign.getsockname()[1]
        result, calls = run(["-Demo"], postgres_port=port)
        assert result.returncode != 0
        assert str(port) in result.stdout + result.stderr
        assert foreign.getsockname()[1] == port
    assert config.read_bytes() == before
    assert not any("build" in args or "up" in args for args in stages(calls))
