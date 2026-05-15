# Deployment Notes

## Persistent clipping data

The app stores learning history and clipping candidates in SQLite.

Default container path:

```text
/app/data/clipping_prototype.sqlite3
```

If your Koyeb plan supports persistent volumes, attach a persistent volume to:

```text
/app/data
```

If your Koyeb plan does not support persistent volumes, use the GitHub JSON backup
flow below. In that setup, `/app/data` is still used as the live SQLite location,
but the durable copy lives in GitHub.

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

Authenticated JSON export API:

```text
/api/storage/export
```

Authenticated JSON import API:

```text
/api/storage/import
```

Import requests replace local storage only when the request body includes:

```json
{
  "payload": { "version": 1, "tables": {} },
  "confirm_replace": true
}
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

## GitHub JSON backup

Use this when Koyeb persistent volumes are unavailable.

### User-configured Koyeb environment variables

Add these exact variables in the Koyeb Service environment settings:

```text
BACKUP_PROVIDER=github
BACKUP_GITHUB_REPO=kentism/navernews-backup
BACKUP_GITHUB_BRANCH=main
BACKUP_FILE_PATH=navernews/clipping_backup.json
BACKUP_GITHUB_TOKEN=ghp_your_token_here
```

Replace `kentism/navernews-backup` with the private GitHub repository that should
store the backup file.

`BACKUP_GITHUB_TOKEN` must be a GitHub token with read/write access to the backup
repository contents. Store it only as a Koyeb environment variable. Do not commit
it to this repository.

Keep these existing app variables too:

```text
APP_DATA_DIR=/app/data
PORT=8000
APP_ACCESS_KEY=...
NAVER_CLIENT_ID=...
NAVER_CLIENT_SECRET=...
```

### Manual backup and restore APIs

Check whether backup is configured:

```text
GET /api/storage/backup/status
```

Upload the current SQLite data as JSON to GitHub:

```text
POST /api/storage/backup
```

Restore the GitHub JSON backup over local SQLite data:

```json
POST /api/storage/restore

{
  "confirm_replace": true
}
```

Restore is intentionally destructive. It replaces local storage with the GitHub
backup and refuses to run unless `confirm_replace` is `true`.

### Suggested verification

1. Add one candidate keyword or finalize one clipping.
2. Open `/api/storage/status` and note the relevant counts.
3. Call `POST /api/storage/backup`.
4. Redeploy or restart the Koyeb service.
5. If counts are gone, call `POST /api/storage/restore` with `confirm_replace: true`.
6. Open `/api/storage/status` again and confirm the counts are back.
