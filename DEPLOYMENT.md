# Deployment Notes

## Persistent clipping data

The app stores learning history and clipping candidates in SQLite.

Default container path:

```text
/app/data/clipping_prototype.sqlite3
```

For Koyeb Docker image deployments, attach a persistent volume to:

```text
/app/data
```

Recommended environment variables:

```text
APP_DATA_DIR=/app/data
PORT=8000
APP_ACCESS_KEY=...
NAVER_CLIENT_ID=...
NAVER_CLIENT_SECRET=...
```

If you want to use an exact DB file path instead of a data directory, set:

```text
CLIPPING_DB_PATH=/app/data/clipping_prototype.sqlite3
```

## Health and storage checks

Container health check path:

```text
/healthz
```

Authenticated storage status API:

```text
/api/storage/status
```

Use the storage status response to verify:

- `data_dir_writable` is `true`
- `db_exists` is `true`
- `db_path` points inside the mounted persistent volume
- counts for `final_clipping_snapshots`, `clipping_candidates`, and `candidate_keywords` remain the same after redeploy/restart

## Persistence test

1. Open the deployed app and finalize one clipping snapshot.
2. Visit `/api/storage/status` while logged in.
3. Confirm the snapshot count increased.
4. Redeploy or restart the Koyeb service.
5. Visit `/api/storage/status` again.
6. Confirm the same DB path and counts are preserved.
