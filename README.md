# WSB Sentiment Tracker

Step-by-step build-out for a WallStreetBets sentiment system and an inverse-meme strategy backtester.

## Current status
Initial project scaffold is in place:
- environment/config loading
- starter database schema
- step-by-step implementation plan

See `docs/STEP_BY_STEP_BUILD.md` for the roadmap.

## Quickstart

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
```

Fill in `.env` with Reddit API keys and database URL.

## Initialize database

```bash
PYTHONPATH=src python scripts/init_db.py
```

## Next implementation steps
1. Add Reddit post ingestion job.
2. Add Reddit comment ingestion job.
3. Add raw-to-clean text normalization pipeline.
4. Add ticker extraction and filtering pipeline.
