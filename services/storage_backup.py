import base64
import json
from urllib.parse import quote

import httpx

from app_config import (
    BACKUP_FILE_PATH,
    BACKUP_GITHUB_BRANCH,
    BACKUP_GITHUB_REPO,
    BACKUP_GITHUB_TOKEN,
    BACKUP_PROVIDER,
    HTTP_TIMEOUT_SECONDS,
)


class BackupConfigError(RuntimeError):
    pass


def get_backup_config_status() -> dict:
    return {
        "provider": BACKUP_PROVIDER or None,
        "configured": is_backup_configured(),
        "github_repo": BACKUP_GITHUB_REPO or None,
        "github_branch": BACKUP_GITHUB_BRANCH or None,
        "file_path": BACKUP_FILE_PATH or None,
        "token_configured": bool(BACKUP_GITHUB_TOKEN),
    }


def is_backup_configured() -> bool:
    if BACKUP_PROVIDER != "github":
        return False
    return bool(BACKUP_GITHUB_TOKEN and BACKUP_GITHUB_REPO and BACKUP_FILE_PATH)


def _ensure_github_configured() -> None:
    if BACKUP_PROVIDER != "github":
        raise BackupConfigError("BACKUP_PROVIDER must be set to github.")
    missing = [
        name
        for name, value in [
            ("BACKUP_GITHUB_TOKEN", BACKUP_GITHUB_TOKEN),
            ("BACKUP_GITHUB_REPO", BACKUP_GITHUB_REPO),
            ("BACKUP_FILE_PATH", BACKUP_FILE_PATH),
        ]
        if not value
    ]
    if missing:
        raise BackupConfigError(f"Missing backup settings: {', '.join(missing)}")


def _github_headers() -> dict:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {BACKUP_GITHUB_TOKEN}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _contents_url() -> str:
    encoded_path = quote(BACKUP_FILE_PATH.strip("/"), safe="/")
    return f"https://api.github.com/repos/{BACKUP_GITHUB_REPO}/contents/{encoded_path}"


async def upload_backup(snapshot: dict) -> dict:
    _ensure_github_configured()

    serialized = json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True)
    encoded_content = base64.b64encode(serialized.encode("utf-8")).decode("ascii")
    url = _contents_url()

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        existing_sha = None
        existing_response = await client.get(
            url,
            headers=_github_headers(),
            params={"ref": BACKUP_GITHUB_BRANCH},
        )
        if existing_response.status_code == 200:
            existing_sha = existing_response.json().get("sha")
        elif existing_response.status_code != 404:
            raise RuntimeError(
                f"GitHub backup lookup failed with status {existing_response.status_code}."
            )

        payload = {
            "message": "Update navernews clipping backup",
            "content": encoded_content,
            "branch": BACKUP_GITHUB_BRANCH,
        }
        if existing_sha:
            payload["sha"] = existing_sha

        response = await client.put(url, headers=_github_headers(), json=payload)
        if response.status_code not in (200, 201):
            raise RuntimeError(f"GitHub backup upload failed with status {response.status_code}.")

        data = response.json()
        content = data.get("content") or {}
        commit = data.get("commit") or {}
        return {
            "provider": "github",
            "repo": BACKUP_GITHUB_REPO,
            "branch": BACKUP_GITHUB_BRANCH,
            "file_path": BACKUP_FILE_PATH,
            "sha": content.get("sha"),
            "commit_sha": commit.get("sha"),
            "html_url": content.get("html_url"),
        }


async def download_backup() -> dict:
    _ensure_github_configured()

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        response = await client.get(
            _contents_url(),
            headers=_github_headers(),
            params={"ref": BACKUP_GITHUB_BRANCH},
        )
        if response.status_code == 404:
            raise FileNotFoundError("Backup file was not found in GitHub.")
        if response.status_code != 200:
            raise RuntimeError(f"GitHub backup download failed with status {response.status_code}.")

    data = response.json()
    raw_content = data.get("content") or ""
    decoded = base64.b64decode(raw_content).decode("utf-8")
    snapshot = json.loads(decoded)
    if not isinstance(snapshot, dict):
        raise ValueError("Backup file does not contain a JSON object.")

    return snapshot
