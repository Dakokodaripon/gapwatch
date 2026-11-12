"""Command line interface: `gapwatch run` and `gapwatch cleanup`."""

from __future__ import annotations

import argparse
import json
import os
import sys

from gapwatch import __version__
from gapwatch.checker import Report, check
from gapwatch.listen_notify import RunConfig, RunResult, cleanup, run


def _format(report: Report, result: RunResult, config: RunConfig) -> str:
    lines = [
        f"gapwatch {__version__} · source: postgres LISTEN/NOTIFY",
        "",
        f"Wrote {report.sent:,} changes and cut the listener's connection "
        f"{len(result.windows)} time(s) (run took {result.duration:.1f}s)",
        "",
        f"  Delivered     {report.delivered:,} ({report.delivery_rate:.2%})",
        f"  Missing       {len(report.missing):,}",
        f"  Duplicated    {sum(c - 1 for c in report.duplicates.values()):,}",
        f"  Out of order  {report.out_of_order:,}",
    ]
    if result.windows:
        lines.append("")
        for i, (window, lost) in enumerate(
            zip(result.windows, report.missing_by_window, strict=True), start=1
        ):
            lines.append(
                f"  Disconnect #{i}: {window.start:5.2f}s → {window.end:5.2f}s "
                f"({window.end - window.start:.2f}s offline), {lost:,} changes missed"
            )
        if report.missing_outside_windows:
            lines.append(f"  Missed outside any disconnect: {report.missing_outside_windows:,}")
    if report.missing_ranges:
        shown = ", ".join(f"{a}" if a == b else f"{a}–{b}" for a, b in report.missing_ranges[:5])
        more = len(report.missing_ranges) - 5
        lines.append("")
        suffix = f" (+{more} more ranges)" if more > 0 else ""
        lines.append(f"  Missing changes: {shown}{suffix}")
    lines.append("")
    lines.append(
        "Result: no changes lost."
        if report.ok
        else "Result: your app would have silently missed these changes."
    )
    return "\n".join(lines)


def _cmd_run(args: argparse.Namespace) -> int:
    config = RunConfig(
        dsn=args.dsn,
        count=args.count,
        rate=args.rate,
        faults=args.faults,
        reconnect_delay=args.reconnect_delay,
        drain=args.drain,
        seed=args.seed,
    )
    result = run(config)
    report = check(result.sent, result.received, result.sent_at, result.windows)
    print(_format(report, result, config))

    if args.json:
        data = report.to_dict()
        data.update(
            run_id=result.run_id,
            source="listen_notify",
            duration_s=round(result.duration, 3),
            disconnects=[
                {"start_s": round(w.start, 3), "end_s": round(w.end, 3)} for w in result.windows
            ],
            config={
                "count": config.count,
                "rate": config.rate,
                "faults": config.faults,
                "reconnect_delay": config.reconnect_delay,
            },
        )
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    return 1 if args.fail_on_loss and not report.ok else 0


def _cmd_cleanup(args: argparse.Namespace) -> int:
    cleanup(args.dsn)
    print("Removed gapwatch_events and gapwatch_notify().")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gapwatch",
        description="Crash-test how database changes reach your app.",
    )
    parser.add_argument("--version", action="version", version=f"gapwatch {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    dsn_help = "Postgres connection string (or set GAPWATCH_DSN)"
    default_dsn = os.environ.get("GAPWATCH_DSN")

    p_run = sub.add_parser("run", help="write changes, cut connections, report what was lost")
    p_run.add_argument("--dsn", default=default_dsn, required=default_dsn is None, help=dsn_help)
    p_run.add_argument("--count", type=int, default=5000, help="changes to write (default 5000)")
    p_run.add_argument("--rate", type=float, default=500, help="changes per second (default 500)")
    p_run.add_argument(
        "--faults", type=int, default=3, help="times to cut the connection (default 3)"
    )
    p_run.add_argument(
        "--reconnect-delay",
        type=float,
        default=1.0,
        help="seconds the listener waits before reconnecting (default 1.0)",
    )
    p_run.add_argument(
        "--drain", type=float, default=2.0, help="seconds to wait for late changes (default 2)"
    )
    p_run.add_argument("--seed", type=int, default=None, help="seed for fault timing")
    p_run.add_argument("--json", metavar="PATH", help="also write the report as JSON")
    p_run.add_argument(
        "--fail-on-loss", action="store_true", help="exit with code 1 if anything was lost"
    )
    p_run.set_defaults(func=_cmd_run)

    p_clean = sub.add_parser("cleanup", help="remove the table and trigger gapwatch created")
    p_clean.add_argument("--dsn", default=default_dsn, required=default_dsn is None, help=dsn_help)
    p_clean.set_defaults(func=_cmd_cleanup)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # keep the CLI output readable
        print(f"gapwatch: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
