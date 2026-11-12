"""Postgres LISTEN/NOTIFY source.

A trigger sends a notification for every row the writer inserts. A listener
receives them the way a typical app does: it reconnects after a failure and
subscribes again. Meanwhile the fault injector cuts the listener's connection
with pg_terminate_backend, so the run shows what a real app would miss.
"""

from __future__ import annotations

import random
import threading
import time
import uuid
from dataclasses import dataclass, field

import psycopg

from gapwatch.checker import Window

CHANNEL = "gapwatch"

SETUP_SQL = f"""
create table if not exists gapwatch_events (
    run_id text not null,
    seq bigint not null,
    created_at timestamptz not null default now(),
    primary key (run_id, seq)
);

create or replace function gapwatch_notify() returns trigger
language plpgsql as $$
begin
    perform pg_notify('{CHANNEL}', new.run_id || ':' || new.seq);
    return new;
end;
$$;

drop trigger if exists gapwatch_notify on gapwatch_events;
create trigger gapwatch_notify
    after insert on gapwatch_events
    for each row execute function gapwatch_notify();
"""

CLEANUP_SQL = """
drop table if exists gapwatch_events;
drop function if exists gapwatch_notify();
"""


@dataclass
class RunConfig:
    dsn: str
    count: int = 5000
    rate: float = 500.0
    faults: int = 3
    reconnect_delay: float = 1.0
    drain: float = 2.0
    seed: int | None = None


@dataclass
class RunResult:
    run_id: str
    sent: list[int] = field(default_factory=list)
    sent_at: dict[int, float] = field(default_factory=dict)
    received: list[int] = field(default_factory=list)
    windows: list[Window] = field(default_factory=list)
    duration: float = 0.0


def setup(dsn: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(SETUP_SQL)


def cleanup(dsn: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(CLEANUP_SQL)


class _Run:
    def __init__(self, config: RunConfig):
        self.config = config
        self.result = RunResult(run_id=uuid.uuid4().hex[:12])
        self.app_name = f"gapwatch-listener-{self.result.run_id}"
        self.start = 0.0
        self.listening = threading.Event()
        self.writer_done = threading.Event()
        self.stop = threading.Event()
        self.kill_times: list[float] = []
        self.resubscribe_times: list[float] = []
        self.errors: list[BaseException] = []

    def now(self) -> float:
        return time.monotonic() - self.start

    # The listener behaves like a typical app: subscribe, and if the
    # connection drops, wait a moment, reconnect and subscribe again.
    def listener(self) -> None:
        prefix = self.result.run_id + ":"
        try:
            while not self.stop.is_set():
                try:
                    with psycopg.connect(
                        self.config.dsn,
                        autocommit=True,
                        application_name=self.app_name,
                    ) as conn:
                        conn.execute(f"listen {CHANNEL}")
                        if self.listening.is_set():
                            self.resubscribe_times.append(self.now())
                        self.listening.set()
                        while not self.stop.is_set():
                            for note in conn.notifies(timeout=0.2):
                                if note.payload.startswith(prefix):
                                    self.result.received.append(int(note.payload[len(prefix) :]))
                except psycopg.OperationalError:
                    if not self.stop.is_set():
                        time.sleep(self.config.reconnect_delay)
        except BaseException as exc:  # surface unexpected errors to the caller
            self.errors.append(exc)
            self.listening.set()

    def writer(self) -> None:
        interval = 1.0 / self.config.rate if self.config.rate > 0 else 0.0
        try:
            with psycopg.connect(self.config.dsn, autocommit=True) as conn:
                next_at = time.monotonic()
                for seq in range(1, self.config.count + 1):
                    conn.execute(
                        "insert into gapwatch_events (run_id, seq) values (%s, %s)",
                        (self.result.run_id, seq),
                    )
                    self.result.sent.append(seq)
                    self.result.sent_at[seq] = self.now()
                    next_at += interval
                    delay = next_at - time.monotonic()
                    if delay > 0:
                        time.sleep(delay)
        except BaseException as exc:
            self.errors.append(exc)
        finally:
            self.writer_done.set()

    def fault_times(self) -> list[float]:
        """Spread the faults across the write period, with a little jitter."""
        n = self.config.faults
        if n <= 0:
            return []
        total = self.config.count / self.config.rate if self.config.rate > 0 else 1.0
        rng = random.Random(self.config.seed)
        slot = total / (n + 1)
        return [slot * (i + 1) + rng.uniform(-0.2, 0.2) * slot for i in range(n)]

    def injector(self) -> None:
        try:
            with psycopg.connect(self.config.dsn, autocommit=True) as conn:
                for at in self.fault_times():
                    delay = at - self.now()
                    if delay > 0 and self.writer_done.wait(delay):
                        return
                    # Take the time before the cut, so changes committed while
                    # the terminate call is in flight count as part of it.
                    cut_at = self.now()
                    cur = conn.execute(
                        "select count(*) from ("
                        " select pg_terminate_backend(pid) from pg_stat_activity"
                        " where application_name = %s and pid <> pg_backend_pid()"
                        ") t",
                        (self.app_name,),
                    )
                    row = cur.fetchone()
                    if row and row[0]:
                        self.kill_times.append(cut_at)
        except BaseException as exc:
            self.errors.append(exc)

    def run(self) -> RunResult:
        self.start = time.monotonic()
        listener = threading.Thread(target=self.listener, daemon=True)
        listener.start()
        if not self.listening.wait(10):
            self.stop.set()
            raise RuntimeError("listener could not subscribe within 10 seconds")
        if self.errors:
            raise self.errors[0]

        writer = threading.Thread(target=self.writer, daemon=True)
        injector = threading.Thread(target=self.injector, daemon=True)
        writer.start()
        injector.start()
        writer.join()
        injector.join()

        # Give in-flight notifications time to arrive before counting.
        time.sleep(self.config.drain)
        self.stop.set()
        listener.join(timeout=5)

        if self.errors:
            raise self.errors[0]

        end = self.now()
        for killed in self.kill_times:
            back = next((t for t in self.resubscribe_times if t >= killed), end)
            self.result.windows.append(Window(start=killed, end=back))
            # Each resubscribe belongs to one fault.
            if back in self.resubscribe_times:
                self.resubscribe_times.remove(back)
        self.result.duration = end
        return self.result


def run(config: RunConfig) -> RunResult:
    setup(config.dsn)
    return _Run(config).run()
