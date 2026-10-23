# 배포와 운영

## 배포 경로

GitHub Actions가 테스트를 실행한 뒤 `ghcr.io/kentism/navernews-web`에 Docker 이미지를 게시한다. Koyeb은 기존 Docker 이미지 배포 방식을 유지한다. Git 푸시, 이미지 게시, Koyeb의 새 이미지 반영은 별개 단계다.

정확한 버전 추적에는 `latest` 대신 커밋 SHA 태그를 사용할 수 있다. 직전 정상 이미지 태그를 기록해 둔다. Docker와 CI의 의존성 설치 기준은 `requirements.lock`이다. 기본 이미지는 기존 `python:3.12-slim`을 유지한다.

## 사용자가 직접 설정하는 환경변수

설정 위치: Koyeb 해당 서비스의 Settings → Environment variables. 로컬에서는 저장소 루트 `.env`.

| 이름 | 예시 | 영향 |
| --- | --- | --- |
| `APP_ACCESS_KEY` | 본인이 정한 비밀번호 | 로그인 인증. 기존 값을 유지하면 현재 로그인 방식이 이어진다. |
| `NAVER_CLIENT_ID` | 네이버 개발자센터 Client ID | 뉴스 검색 인증 |
| `NAVER_CLIENT_SECRET` | 네이버 개발자센터 Client Secret | 뉴스 검색 인증 |
| `PORT` | `8000` | HTTP 수신 포트 |
| `POLLING_INTERVAL_SECONDS` | `30` | 알림 검색 주기 |
| `APP_DATA_DIR` | `/app/data` | 이전 DB 내보내기를 위한 위치. 신규 학습 저장 용도가 아니다. |
| `CLIPPING_DB_PATH` | `/app/data/clipping_prototype.sqlite3` | 이전 DB 경로를 별도로 지정할 때만 설정 |

현재 개편을 위해 새 API 키나 외부 저장소를 추가할 필요는 없다. `BACKUP_*` 환경변수는 현재 코드에서 사용하지 않는다. 기존 버전으로 돌아갈 가능성이 있으면 이전 값은 별도로 보관한 후 정리한다.

## 상태 확인

- `GET /healthz`: 로그인 없이 HTTP 200과 `mode: search_clipping`을 확인한다.
- `GET /api/storage/status`: 로그인 후 현재 초안 저장 방식과 이전 DB 존재/건수를 확인한다.
- `GET /api/storage/export`: 로그인 후 남아 있는 이전 SQLite 데이터를 JSON으로 내려받는다. 읽기 전용이다.

학습용 GitHub 자동 백업, 자동 복원, 저장/수정/삭제 API는 종료했다. 앱 시작은 GitHub 토큰이나 이전 DB 유무에 의존하지 않는다. 기존 GitHub 저장소는 자동 변경하거나 삭제하지 않는다.

## 클리핑 보관

- 브라우저 `localStorage`: 작성 중인 문서, 검색어·테마·알림 설정.
- TXT 파일: 사용자가 `파일 저장`으로 보관한 클리핑 문서.
- 기존 서버 DB: 읽기 전용 이전 이력. 재배포/컨테이너 교체로 컨테이너 내부 파일이 보존되는 것은 아니므로 필요하면 먼저 내보낸다.
- 기존 GitHub 백업: 과거 자료. 현재 버전이 자동 동기화하지 않는다.

기존 데이터 위치에 대한 볼륨 설정은 그대로 유지해도 된다. 기존 환경에서 영구 볼륨이 지원되지 않으면 배포 전에 이전 DB를 내보내야 한다.

## 변경 전 복구 자료

이번 작업의 로컬 백업은 `backups/pre-learning-retirement-2026-10-23/`에 있다. ZIP, Git bundle, 로컬 SQLite 사본, 운영 서버 JSON 내보내기, SHA-256 manifest를 포함한다. 실제 `.env` 값과 접근할 수 없었던 과거 GitHub 원격 파일은 포함하지 않는다. 복구 절차는 `docs/learning-retirement.md`에 기록했다.
