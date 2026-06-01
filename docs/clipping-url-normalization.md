# 클리핑 URL 정리

클리핑 양식에 들어가는 기사 원문 URL은 저장 전에 추적용 쿼리 파라미터를 정리한다.

## 정리 기준

- `utm_`으로 시작하는 쿼리 파라미터만 제거한다.
- `idxno`, `article_id`, `aid`, `mod`처럼 기사 식별이나 페이지 렌더링에 쓰일 수 있는 파라미터는 보존한다.
- URL 전체의 `?` 이하를 삭제하지 않는다.

## 적용 위치

- 브라우저 클리핑 생성 시 `static/js/clipping_service.js`에서 URL을 정리한다.
- 최종본 학습 시 `services/clipping_store.py`에서 한 번 더 URL을 정리한다.
- 기사 저장과 최종본 매칭도 정리된 URL 기준을 함께 사용한다.

## 예시

```text
https://press.example.com/view?idxno=123&utm_source=naver&utm_medium=referral
```

위 URL은 다음처럼 저장된다.

```text
https://press.example.com/view?idxno=123
```

이 처리는 클리핑 표기의 가독성을 높이면서도 기사 식별에 필요한 쿼리는 유지하기 위한 것이다.
