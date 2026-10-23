const test = require('node:test');
const assert = require('node:assert/strict');
const doc = require('../static/js/clipping_document.js');

test('일괄 클리핑은 기존 분류와 기사 순서를 보존한다', () => {
    const articles = [1, 2].map(number => ({ title: `기사 ${number}`, source: '매체', link: `https://example.com/${number}` }));
    const result = doc.insertArticles(doc.emptyText, articles, '방송·통신 관련');
    assert.equal(result.added, 2);
    assert.ok(result.text.indexOf('■ 방송·통신 관련') < result.text.indexOf('기사 1'));
    assert.ok(result.text.indexOf('기사 1') < result.text.indexOf('기사 2'));
    assert.ok(result.text.indexOf('기사 2') < result.text.indexOf('■ 유관기관 관련'));
});
test('같은 URL만 중복 정리하고 유사 제목의 다른 기사는 유지한다', () => {
    const articles = [{ title: '동일한 사건', link: 'https://example.com/1?utm_source=naver' },
        { title: '동일한 사건', link: 'https://example.com/1' }, { title: '동일한 사건', link: 'https://example.com/2' }];
    const first = doc.insertArticles('', articles, '기타');
    assert.equal(first.added, 2);
    assert.equal(doc.insertArticles(first.text, articles, '기타').added, 0);
});
test('기사 날짜는 한국 시간을 기준으로 표기한다', () => {
    assert.match(doc.buildEntry({ title: '기사', link: 'https://example.com/1', pubDate: '2026-10-22T23:00:00Z' }), /\(10\.23\.\)/);
});
test('URL의 기사 식별값은 보존하고 실행 가능한 프로토콜은 거부한다', () => {
    assert.equal(doc.normalizeUrl('https://example.com/view?id=1&ref=NAVER&utm_source=test'), 'https://example.com/view?id=1&ref=NAVER');
    assert.equal(doc.normalizeUrl('javascript:alert(1)'), '');
});
test('대량 기사는 한 번의 문서 갱신에 사용할 문자열로 생성한다', () => {
    const items = Array.from({ length: 1000 }, (_, index) => ({ title: `기사 ${index}`, link: `https://example.com/${index}` }));
    const result = doc.insertArticles(doc.emptyText, items, '기타');
    assert.equal(result.added, 1000);
    assert.equal((result.text.match(/^▷ /gm) || []).length, 1000);
});
