# gapwatch

**Crash-test how database changes reach your app.**

Live dashboards, chat, order tracking and notifications all depend on database changes reaching the app. When a connection drops or a server restarts, some of those changes can disappear without any error. Nobody notices until a user says "my screen didn't update."

gapwatch measures it. It writes numbered changes to your database, listens the way your app does, cuts the connection on purpose, and tells you exactly what never arrived.

```
$ gapwatch run --dsn postgresql://localhost/postgres

gapwatch 0.1.0 · source: postgres LISTEN/NOTIFY

Wrote 5,000 changes and cut the listener's connection 3 time(s) (run took 12.1s)

  Delivered     3,492 (69.84%)
  Missing       1,508
  Duplicated    0
  Out of order  0

  Disconnect #1:  2.64s →  3.65s (1.01s offline), 502 changes missed
  Disconnect #2:  4.53s →  5.53s (1.01s offline), 503 changes missed
  Disconnect #3:  7.28s →  8.28s (1.01s offline), 503 changes missed

  Missing changes: 1317–1818, 2259–2761, 3634–4136

Result: your app would have silently missed these changes.
```

That's a real run against Postgres 16, with a listener that waits one second before reconnecting, like many apps do.

**Reconnecting faster doesn't fix it.** With `--reconnect-delay 0`, the listener was back within about 10 milliseconds each time, and it still lost 3 changes per disconnect (9 of 5,000). Without any faults, all 5,000 arrived. The changes are lost in the gap itself, however short it is.

## Quick start

```bash
pip install gapwatch    # or, until the first release: pip install git+https://github.com/Dakokodaripon/gapwatch
gapwatch run --dsn "postgresql://user:password@host:5432/dbname"
gapwatch cleanup --dsn "..."
```

You can also set `GAPWATCH_DSN` instead of passing `--dsn`.

**Use a test or staging database.** gapwatch creates a table called `gapwatch_events` and a trigger. `gapwatch cleanup` removes both.

## Running against Supabase

gapwatch works with a Supabase database, since it's Postgres underneath. This tests Postgres LISTEN/NOTIFY on your Supabase database. Support for Supabase Realtime itself is on the roadmap.

1. In your Supabase project, open **Connect** and copy the **Direct connection** string (or the **Session pooler** one if your network has no IPv6).
2. Run:

```bash
gapwatch run --dsn "postgresql://postgres:YOUR_PASSWORD@db.YOUR_PROJECT_REF.supabase.co:5432/postgres"
gapwatch cleanup --dsn "..."
```

Don't use the **Transaction pooler** (port 6543). It doesn't support LISTEN, so the listener can't subscribe.

Use a test or development project, not production.

## Options

| Option | Default | What it does |
| --- | --- | --- |
| `--count` | 5000 | How many changes to write |
| `--rate` | 500 | Changes per second (0 means as fast as possible) |
| `--faults` | 3 | How many times to cut the listener's connection |
| `--reconnect-delay` | 1.0 | Seconds the listener waits before reconnecting |
| `--drain` | 2.0 | Seconds to wait for late changes before counting |
| `--seed` | none | Makes the timing of faults repeatable |
| `--json PATH` | none | Also write the report as JSON |
| `--fail-on-loss` | off | Exit with code 1 if anything was lost, for use in CI |

## How it works

1. A trigger sends a notification for every row gapwatch inserts, each carrying a sequence number.
2. A listener subscribes the way a typical app does. If its connection drops, it waits, reconnects and subscribes again.
3. While changes are being written, gapwatch ends the listener's connection with `pg_terminate_backend`, the same thing that happens when a server restarts or a connection is killed.
4. The checker compares what was sent with what arrived, and works out which disconnect each missing change belongs to.

In systems engineering terms, it's fault-injection testing for realtime data delivery: it measures loss, duplication and ordering under degraded connectivity.

## Is this a Postgres bug?

No. Postgres documents that notifications are only delivered to sessions that are listening at the time. gapwatch makes that behaviour visible and measurable, so you can decide whether your app needs a way to catch up, such as re-reading recent rows after reconnecting.

## Roadmap

Version 0.1 tests Postgres `LISTEN/NOTIFY`. Next:

- Supabase Realtime
- Debezium and Kafka
- Logical replication consumers
- Network faults (latency, packet loss) as well as connection kills
- A catch-up mode, to measure whether a recovery strategy actually closes the gap

Ideas and results from your own setup are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT