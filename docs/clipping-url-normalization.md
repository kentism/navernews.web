# 클리핑 URL 정리

클리핑 양식에 들어가는 기사 원문 URL은 저장 전에 추적용 쿼리 파라미터를 정리한다.

## 정리 기준

- `utm_`으로 시작하는 쿼리 파라미터만 제거한다.
- `idxno`, `article_id`, `aid`, `mod`처럼 기사 식별이나 페이지 렌더링에 쓰일 수 있는 파라미터는 보존한다.
- URL 전체의 `?` 이하를 삭제하지 않는다.

## 적용 위치

- 브라우저 클리핑 문서 생성 시 `static/js/clipping_document.js`에서 URL을 정리한다.
- 기간 수집 시 `utils/article_urls.py`에서 동일 원문 URL을 판별한다.
- 학습/서버 기사 저장은 종료했으며, 서로 다른 URL의 유사 기사는 제거하지 않는다.

## 예시

```text
https://press.example.com/view?idxno=123&utm_source=naver&utm_medium=referral
```

위 URL은 다음처럼 저장된다.

```text
https://press.example.com/view?idxno=123
```

이 처리는 클리핑 표기의 가독성을 높이면서도 기사 식별에 필요한 쿼리는 유지하기 위한 것이다.
