const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readKeywords, addKeyword, renameKeyword, normalizeKeywords } = require('../static/js/home_keywords.js');

test('처음 접속할 때만 기본 검색어를 사용하고 빈 저장 목록도 유지한다', () => {
    assert.deepEqual(readKeywords(null, ['기본']), ['기본']);
    assert.deepEqual(readKeywords('[]', ['기본']), []);
});
test('저장값이 손상되었거나 배열이 아니면 기본값으로 복구한다', () => {
    for (const raw of ['broken', '{}', 'null']) assert.deepEqual(readKeywords(raw, ['기본']), ['기본']);
});
test('검색어는 앞뒤 공백과 중복을 정리하고 최대 8개만 유지한다', () => {
    assert.deepEqual(normalizeKeywords([' 정책 ', '정책', '', null, 1, '법안']), ['정책', '법안']);
    assert.equal(normalizeKeywords(Array.from({ length: 12 }, (_, i) => `검색${i}`)).length, 8);
});
test('9번째 검색어와 중복 입력은 기존 목록을 바꾸지 않는다', () => {
    const keywords = Array.from({ length: 8 }, (_, i) => `검색${i}`);
    assert.ok(addKeyword(keywords, '추가').error);
    assert.deepEqual(addKeyword(keywords, '추가').keywords, keywords);
    assert.ok(addKeyword(['정책'], ' 정책 ').error);
});
test('빈 검색어와 API 한도를 초과한 검색어를 거부한다', () => {
    assert.ok(addKeyword([], ' ').error);
    assert.ok(addKeyword([], '가'.repeat(301)).error);
    assert.equal(addKeyword([], '가'.repeat(300)).keywords.length, 1);
});
test('검색어 수정은 순서를 유지하고 다른 행과의 중복을 거부한다', () => {
    assert.deepEqual(renameKeyword(['정책', '법안'], 0, ' 새 정책 ').keywords, ['새 정책', '법안']);
    assert.ok(renameKeyword(['정책', '법안'], 0, '법안').error);
    assert.ok(renameKeyword(['정책'], 0, '').error);
});
test('저장된 문자열은 HTML로 해석하지 않고 그대로 유지한다', () => {
    assert.deepEqual(readKeywords('["<img src=x>"]', []), ['<img src=x>']);
});
