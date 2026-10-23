# 뉴스 클리핑

FastAPI + Jinja2 + vanilla JavaScript 기반의 내부 뉴스 검색/클리핑 도구다.

## 현재 기능

- 검색어별 탭, 포함/제외 검색, 최신순 추가 조회.
- 홈에서 검색어 최대 15개 저장/수정/삭제와 전체 검색. 동시 처리 3개, 진행 상태/실패 재시도와 열린 탭 목록을 제공한다. 접속 시 자동 검색하지 않는다.
- 한국 시간 기준 날짜 범위 조회와 조회 한도/완료 여부 표시.
- 기사별 분류 지정 클리핑. 동일 URL은 정리하고 서로 다른 기사는 유지한다.
- 모든 뉴스 카드에 수동 제목 확인 버튼 제공. 제목이 잘린 경우 이용하며, 지원 사이트의 확인 제목을 선택한 경우에만 클리핑에 사용한다. 원래 제목은 보존한다.
- 기존 WYSIWYG 편집, 일반 텍스트 복사, URL 제외 복사, TXT 파일 저장.
- 브라우저 초안 저장 상태 표시와 편집기 외부 리소스 실패 시 텍스트 편집 대체.
- 검색어 추적, 토스트/브라우저 알림, 클리핑 탭 내 알림 관리.
- 기존 학습 DB의 읽기 전용 내보내기.

개인화 학습과 자동 후보 선별은 2026-10-23에 종료했다. 클리핑 클릭이나 문서 편집은 서버 학습 데이터를 생성하지 않는다.

## 실행

Python 3.12 환경에서 다음을 실행한다.

```powershell
python -m pip install -r requirements.lock
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

`.env.example`에 설정 이름을 기록했다. 실제 값은 저장소 루트 `.env` 또는 배포 서비스 환경변수에 설정한다.

## 검증

```powershell
python -m unittest discover -s tests -p "test_*.py"
node --test tests/clipping_copy_formatter.test.js tests/clipping_document.test.js tests/home_keywords.test.js tests/search_batch.test.js tests/ui_motion.test.js tests/article_titles.test.js
```

GitHub Actions는 Python/Node 테스트와 JS 문법 검사 통과 후 Docker 이미지를 생성한다.

## 데이터와 문서

작성 중인 클리핑은 현재 브라우저에 저장된다. 브라우저 데이터 삭제나 다른 기기로의 이동에 대비하려면 클리핑 탭의 `파일 저장`을 사용한다. 이전 SQLite와 GitHub 백업은 새로운 학습에 사용하지 않는다.

- [검색과 클리핑](docs/search-and-clipping.md)
- [검색 작업공간과 UI](docs/workspace-ui.md)
- [UI 모션과 로딩 상태](docs/ui-motion.md)
- [구조 개선과 이전 버전 복구](docs/learning-retirement.md)
- [배포 설정](DEPLOYMENT.md)
- [복사 형식](docs/clipping-copy-formats.md)
- [언론사 매칭](docs/media-domain-map.md)
- [뉴스 카드의 수동 제목 확인](docs/article-title-confirmation.md)
- [기사 제목 확인 프로토타입](docs/article-title-prototype.md) (로컬 진단 실행 도구)

## 코드 위치

- `routers/`: 인증, 화면, 검색/알림 API와 읽기 전용 이전 이력 내보내기.
- `services/`: 네이버 검색, 날짜 범위 수집, 모니터링, 언론사 매칭, 이전 DB 읽기.
- `templates/`: 초기 화면 및 기사 목록 HTML.
- `static/js/`: 화면 상태와 작업별 브라우저 동작. 문서 변환과 편집기 연동을 분리한다.
- `static/css/`: 기존 모노톤 스타일과 모바일 레이아웃.
- `utils/`: 검색/템플릿 필터와 URL 정리.
- `tests/`: 외부 통신을 대체한 단위/통합 테스트.
- `docs/`: 기능, 운영, 구조 변경과 복구 절차.
- `data/`: 보관 중인 이전 SQLite. 앱 시작 시 생성하거나 변경하지 않는다.
