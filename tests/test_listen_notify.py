"""Runs against a real Postgres. Skipped unless GAPWATCH_TEST_DSN is set."""

import os

import pytest

from gapwatch.checker import check
from gapwatch.cli import main
from gapwatch.listen_notify import RunConfig, cleanup, run

DSN = os.environ.get("GAPWATCH_TEST_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="set GAPWATCH_TEST_DSN to run")


@pytest.fixture(autouse=True)
def _clean():
    yield
    cleanup(DSN)


def test_no_faults_means_nothing_lost():
    result = run(RunConfig(dsn=DSN, count=300, rate=0, faults=0, drain=1.0))
    report = check(result.sent, result.received)
    assert report.ok, report.to_dict()
    assert result.windows == []


def test_cutting_the_connection_loses_changes_inside_the_window():
    result = run(RunConfig(dsn=DSN, count=1000, rate=200, faults=2, reconnect_delay=0.5, seed=1))
    report = check(result.sent, result.received, result.sent_at, result.windows)
    assert len(result.windows) == 2
    assert report.missing, "expected LISTEN/NOTIFY to miss changes while disconnected"
    # Nearly every lost change should fall inside a disconnect window.
    assert sum(report.missing_by_window) >= len(report.missing) * 0.9
    assert report.duplicates == {}


def test_cli_exit_code_reflects_loss(tmp_path):
    out = tmp_path / "report.json"
    code = main(
        [
            "run",
            "--dsn",
            DSN,
            "--count",
            "400",
            "--rate",
            "200",
            "--faults",
            "1",
            "--reconnect-delay",
            "0.5",
            "--json",
            str(out),
            "--fail-on-loss",
        ]
    )
    assert code == 1
    assert out.exists()
