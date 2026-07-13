const test = require('node:test');
const assert = require('node:assert/strict');

const { formatClippingText } = require('../static/js/clipping_copy_formatter.js');

test('일반 복사는 Markdown 표현을 제거하고 URL을 평문으로 유지한다', () => {
    const source = [
        '**■ 유관기관 관련**',
        '',
        '▷ CPBC : 기사 제목 (06.21.)',
        '',
        '<https://news.cpbc.co.kr/article/1173789?division=NAVER>'
    ].join('\n');

    assert.equal(formatClippingText(source), [
        '■ 유관기관 관련',
        '',
        '▷ CPBC : 기사 제목 (06.21.)',
        '',
        'https://news.cpbc.co.kr/article/1173789?division=NAVER'
    ].join('\n'));
});

test('Markdown 링크의 표시 문구와 관계없이 실제 URL만 복사한다', () => {
    const url = 'https://news.example.com/article/1?ref=A';

    assert.equal(formatClippingText(`[URL](${url})`), url);
    assert.equal(formatClippingText(`[${url}](${url})`), url);
});

test('URL 제외 복사는 지원하는 모든 단독 URL 형식을 제거한다', () => {
    const source = [
        '▷ 언론사 : 기사 제목1 (06.21.)',
        '<https://news.example.com/1>',
        '',
        '▷ 언론사 : 기사 제목2 (06.22.)',
        '[URL](https://news.example.com/2)',
        '',
        '▷ 언론사 : 기사 제목3 (06.23.)',
        'https://news.example.com/3'
    ].join('\n');

    assert.equal(formatClippingText(source, { includeUrls: false }), [
        '▷ 언론사 : 기사 제목1 (06.21.)',
        '',
        '▷ 언론사 : 기사 제목2 (06.22.)',
        '',
        '▷ 언론사 : 기사 제목3 (06.23.)'
    ].join('\n'));
});

test('복사 변환은 입력 Markdown을 변경하지 않는다', () => {
    const source = '**■ 기타**\n\n<https://example.com/article>';

    formatClippingText(source);

    assert.equal(source, '**■ 기타**\n\n<https://example.com/article>');
});

test('기사 제목에 포함된 일반 밑줄은 제거하지 않는다', () => {
    const source = '▷ 언론사 : service_name 업데이트 (06.23.)';

    assert.equal(formatClippingText(source), source);
});
