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

The sync is atomic for managed resource directories. If any source download fails,
the repository content is left unchanged.
