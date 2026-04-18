# Rules

This repository mirrors raw Quantumult X resources referenced by
`quantumult_20260331175325-2.conf`.

## Layout

- `filter/`: entries from `[filter_remote]`
- `rewrite/`: entries from `[rewrite_remote]`
- `sources.json`: source manifest generated from the config file

## Manual sync

```bash
python3 scripts/sync_quantumult_resources.py
```

Each source is synced independently. Successful sources are updated, failed
sources are left untouched, and the GitHub Actions commit message records both
the updated files and failed sources.
