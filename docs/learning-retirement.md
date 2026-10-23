# 학습 기능 종료와 복구 자료

## 결정

2026-10-23 사용자 승인에 따라 개인화 학습과 자동 후보 선별을 종료했다. 최근 제목/출처의 규칙 점수 대신 검색·기간 조회·수동 선택·클리핑에 집중한다.

학습 탭, 최종본 학습 버튼, 후보 점수와 반영/제외 이력, 클릭 시 서버 기록, 학습용 GitHub 자동 백업/복원, 관련 쓰기 API를 제거했다. 기존 데이터 테이블을 DROP하거나 데이터를 삭제하는 마이그레이션은 실행하지 않는다.

일반 클리핑 편집과 복사는 유지한다. 과거 후보 수집의 실용적인 부분은 검색 탭의 날짜 조회와 선택 기사 일괄 클리핑으로 대체했다. 관련 기사 자동 묶음은 현재 화면에서 사용하지 않으며, 다른 URL의 비슷한 기사는 각각 확인할 수 있다.

## 백업 내용

위치: `backups/pre-learning-retirement-2026-10-23/`.

- `workspace.zip`: 변경 전 추적 파일 및 미추적 보고서/내보내기 파일. 62개 파일.
- `repository.bundle`: 커밋 `3efa19005d4ce5e85b067b05de05d0b46438da52`까지의 전체 Git 이력. `git bundle verify`로 확인했다.
- `clipping_prototype.sqlite3`: SQLite backup API로 만든 로컬 DB 사본.
- `production-storage.json`: 변경 전 운영 서비스의 인증된 읽기 API로 내보낸 서버 데이터.
- `manifest.json`: 원본 커밋과 파일별 SHA-256.

`.env`의 실제 값은 포함하지 않는다. 기존 운영 환경변수는 이번 작업에서 변경하지 않았다. 점검 당시 GitHub 원격 백업 인증은 401로 실패했기 때문에 해당 원격 파일의 별도 확보 여부는 미확인이다. 기존 원격 저장소는 수정하지 않았다.

백업 폴더는 Git과 Docker 빌드에서 제외한다. 이 로컬 백업이 원격에 자동 복제되는 것은 아니다.

## 이전 버전 복구

현재 작업 디렉터리와 분리한 위치에서 복구한다. 현재 작업을 강제로 초기화하지 않는다.

```powershell
git clone backups/pre-learning-retirement-2026-10-23/repository.bundle restored-project
```

변경 전 미추적 파일까지 필요하면 ZIP을 새 복구 폴더에 푼다. `.env`는 기존에 보관한 환경변수로 설정한다. 로컬 DB 복구가 필요하면 사본을 복구 프로젝트의 `data/clipping_prototype.sqlite3`로 배치한다. 운영 JSON은 이전 버전의 수동 import와 호환되는 `snapshot`을 포함하지만, 실제 운영 데이터 덮어쓰기는 별도 확인 후 수행한다.

기존 운영 앱은 이번 작업에서 배포하지 않았다. 배포 후 되돌릴 경우 Koyeb에서 이전 정상 GHCR 이미지 태그를 선택하는 방식과 로컬 소스 복구는 별개다.

## 역할 분리

- `main.py`: 앱과 lifespan, 라우터 조립.
- `services/news_service.py`: 외부 뉴스 API와 원본 페이지 메타데이터.
- `services/search_collection.py`: 한국 날짜 범위 수집과 동일 URL 정리.
- `services/monitoring.py`: 알림 폴링과 메모리 상태.
- `services/legacy_archive.py`: 기존 SQLite의 읽기 전용 상태/내보내기.
- `static/js/main.js`: 검색 탭과 페이지 추가 조회.
- `static/js/search_collection.js`: 기간 조회와 선택 작업.
- `static/js/notifications.js`: 검색어 추적과 알림.
- `static/js/clipping_document.js`: 순수 클리핑 문서 변환.
- `static/js/clipping_service.js`: 편집기, 초안 저장, 복사와 파일 내보내기.

## 배포 검증과 의존성

Python 3.12 격리 환경에서 검증하며, 직접 의존성과 하위 의존성을 고정한다. 기존 환경의 버전을 OSV 공개 취약점 API로 조회한 결과 6개 패키지에 경고가 있어 FastAPI/Starlette, AnyIO, python-multipart, certifi, idna, soupsieve를 호환되는 수정 버전으로 갱신했다. 2026-10-23 재조회 시 설치된 앱 의존성 25개에 알려진 취약점 응답은 없었다. 조회 기준은 OSV이며 모든 유형의 보안 문제 부재를 뜻하지는 않는다.

참고: [OSV API](https://google.github.io/osv.dev/api/), [PyPI](https://pypi.org/).

Docker 기본 이미지 자체의 취약점 검사는 별도이며, 이 환경에서 Docker 이미지 빌드/컨테이너 실행은 수행하지 않았다.

최종 검증에서 Python 단위/통합 테스트 40개, Node 문서/복사 테스트 10개, JS 문법 검사와 의존성 충돌 검사를 통과했다. 별도 브라우저 검증에서는 외부 뉴스와 편집기 리소스를 로컬 자료로 대체해 데스크톱/모바일, 다크 테마, 기존 초안과 새로고침 보존, 일괄 클리핑, 복사 두 형식, TXT 다운로드를 확인했다. 조회 한도 표시, 조회 실패 시 기존 결과/선택 보존, 편집기 대체 입력란, 저장 공간 오류 상태도 확인했다.

Starlette의 테스트 도구에서는 기존 `httpx` 호환 경로에 대한 향후 지원 종료 경고가 출력된다. 현재 고정 버전에서는 테스트가 통과하며 운영 검색 클라이언트에는 해당되지 않는다. 다음 테스트 도구 갱신 시 `httpx2` 전환 여부를 함께 검토한다.
