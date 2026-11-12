# Contributing

Thanks for helping. Bug reports, new sources and better fault types are all welcome.

## Setup

```bash
git clone https://github.com/Dakokodaripon/gapwatch
cd gapwatch
pip install -e ".[dev]"
```

The checker tests run without a database. The Postgres tests need a database you can create tables in:

```bash
export GAPWATCH_TEST_DSN="postgresql://postgres:postgres@localhost:5432/postgres"
pytest -q
```

Before opening a pull request:

```bash
ruff check .
ruff format .
pytest -q
```

## Adding a source

A source writes numbered changes and listens for them the way a real app would. Look at `src/gapwatch/listen_notify.py`: it returns what was sent, what was received, and when the listener was disconnected. `checker.py` does the rest. Please open an issue first so we can agree on the shape before you build it.

## Reporting results

If you run gapwatch against a service and get surprising numbers, open an issue with the command you ran, the JSON report and the versions involved. Please leave out connection strings and anything secret. I'll review it as soon as I can.
