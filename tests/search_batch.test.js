const { test } = require('node:test');
const assert = require('node:assert/strict');
const { runBatch, normalizeKeywords, LIMIT } = require('../static/js/search_batch.js');

test('15개 한도와 공백/중복 정리는 저장과 검색에서 동일하다', () => {
    assert.equal(LIMIT, 15);
    assert.deepEqual(normalizeKeywords([' 정책 ', '정책', null, '', 1]), ['정책']);
    assert.equal(normalizeKeywords(Array.from({ length: 20 }, (_, i) => `검색${i}`)).length, 15);
});
test('검색은 최대 3개씩 처리하며 진행률과 결과 순서를 보존한다', async () => {
    const waiting = [];
    const seen = [];
    const progress = [];
    let active = 0;
    let peak = 0;
    const pending = runBatch(['a', 'b', 'c', 'd', 'e'], async keyword => {
        active++; peak = Math.max(peak, active); seen.push(keyword);
        await new Promise(resolve => waiting.push(() => { active--; resolve(); }));
        return 'loaded';
    }, update => progress.push(update));
    assert.deepEqual(seen, ['a', 'b', 'c']);
    waiting.shift()();
    await new Promise(resolve => setImmediate(resolve));
    assert.deepEqual(seen, ['a', 'b', 'c', 'd']);
    while (waiting.length) { waiting.shift()(); await new Promise(resolve => setImmediate(resolve)); }
    const result = await pending;
    assert.equal(peak, 3);
    assert.deepEqual(result.results.map(item => item.keyword), ['a', 'b', 'c', 'd', 'e']);
    assert.deepEqual(progress.map(update => update.completed), [0, 1, 2, 3, 4, 5]);
});
test('일부 오류가 발생해도 계속 진행하고 실패 검색어만 재시도할 수 있다', async () => {
    const result = await runBatch(['정상', '오류', '재사용', '취소'], async keyword => {
        if (keyword === '오류') throw new Error('mock');
        return keyword === '재사용' ? 'reused' : keyword === '취소' ? 'cancelled' : 'loaded';
    });
    assert.equal(result.completed, 4);
    assert.deepEqual(result.failed, ['오류']);
    assert.equal(result.reused, 1);
    assert.equal(result.cancelled, 1);
    const retried = [];
    const retry = await runBatch(result.failed, async keyword => { retried.push(keyword); return 'loaded'; });
    assert.deepEqual(retried, ['오류']);
    assert.deepEqual(retry.failed, []);
});
test('빈 목록과 중복 입력은 불필요한 검색을 만들지 않는다', async () => {
    let calls = 0;
    const worker = async () => { calls++; return 'loaded'; };
    assert.equal((await runBatch([], worker)).total, 0);
    assert.equal((await runBatch([' 정책 ', '정책', '법안'], worker)).total, 2);
    assert.equal(calls, 2);
});
test('호출자가 한도를 초과해 넘겨도 15개만 처리한다', async () => {
    const result = await runBatch(Array.from({ length: 20 }, (_, i) => `검색${i}`), async () => 'loaded');
    assert.equal(result.total, 15);
    assert.equal(result.loaded, 15);
});
