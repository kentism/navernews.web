const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { createTitleChecks } = require('../static/js/article_titles.js');

const short = '방송 정책 개선을 위한 새로운 제도와 향후...';
const full = '방송 정책 개선을 위한 새로운 제도와 향후 추진 계획 발표';
const confirmed = { status: 'confirmed', title: full, source: 'original', source_url: 'https://news.kbs.co.kr/a' };

function fixture(responder = async () => confirmed) {
    const calls = [], timers = new Map();
    const env = {
        FormData, AbortController,
        setTimeout(callback) { const id = Symbol(); timers.set(id, callback); return id; },
        clearTimeout(id) { timers.delete(id); },
        NewsUI: { async request(url, options) { calls.push({ url, options }); return { json: async () => responder(options) }; } },
        NewsMotion: { setBusy(button, busy) { button.busy = busy; } }
    };
    const checks = createTitleChecks(env);
    function makeCard(key = 'same-article') {
        const status = { textContent: '' }, title = { textContent: '' }, source = {}, label = { textContent: '제목 확인' };
        const content = { hidden: true }, checkbox = { checked: false }, attributes = {};
        const panel = { hidden: true, querySelector(selector) {
            return { '[data-title-status]': status, '[data-confirmed-title]': title, '[data-title-source]': source,
                '[data-confirmed-content]': content, '[data-use-confirmed-title]': checkbox }[selector];
        } };
        const card = { isConnected: true, dataset: { title: short }, querySelector(selector) {
            return { '[data-title-result]': panel, '[data-use-confirmed-title]': checkbox, '[data-title-confirm]': button }[selector];
        } };
        const button = { dataset: { titleKey: key, titleToken: 'signed-capability' }, disabled: false,
            closest: () => card, querySelector: () => label,
            setAttribute(name, value) { attributes[name] = value; }, removeAttribute(name) { delete attributes[name]; } };
        checkbox.closest = () => card;
        const clipButton = { closest: () => card };
        return { card, button, panel, checkbox, clipButton, status, title, source, label, content, attributes };
    }
    return { checks, env, calls, timers, makeCard };
}

test('초기화와 카드 표시만으로 외부 조회를 하지 않는다', () => {
    const f = fixture(), c = f.makeCard();
    assert.equal(f.calls.length, 0);
    assert.equal(f.checks.clippingTitle(c.clipButton, short), short);
    assert.equal(c.panel.hidden, true);
});

test('확인 결과는 평문과 출처로 표시하고 선택 전에는 원래 제목을 클리핑한다', async () => {
    const f = fixture(), c = f.makeCard();
    await f.checks.confirm(c.button);
    assert.equal(f.calls.length, 1);
    assert.equal(f.calls[0].url, '/api/search/title-confirmation');
    assert.deepEqual([...f.calls[0].options.body.keys()], ['token']);
    assert.equal(c.title.textContent, full);
    assert.equal(c.source.textContent, '언론사 원문');
    assert.equal(c.card.dataset.title, short);
    assert.equal(c.checkbox.checked, false);
    assert.equal(c.button.disabled, false);
    assert.equal(c.button.busy, false);
    assert.equal(f.timers.size, 0);
    assert.equal(f.checks.clippingTitle(c.clipButton, short), short);
    c.checkbox.checked = true; f.checks.selectionChanged(c.checkbox);
    assert.equal(f.checks.clippingTitle(c.clipButton, short), full);
    assert.equal(c.label.textContent, '확인 제목 사용');
    c.checkbox.checked = false; f.checks.selectionChanged(c.checkbox);
    assert.equal(f.checks.clippingTitle(c.clipButton, short), short);
});

test('결과 접기와 다시 펼치기는 재조회하지 않고 선택을 유지한다', async () => {
    const f = fixture(), c = f.makeCard();
    await f.checks.confirm(c.button);
    c.checkbox.checked = true;
    await f.checks.confirm(c.button);
    assert.equal(c.panel.hidden, true);
    assert.equal(f.checks.clippingTitle(c.clipButton, short), full);
    await f.checks.confirm(c.button);
    assert.equal(c.panel.hidden, false);
    assert.equal(f.calls.length, 1);
});

test('같은 기사의 동시 확인은 하나의 요청을 공유한다', async () => {
    let release;
    const f = fixture(() => new Promise(resolve => { release = resolve; }));
    const first = f.makeCard(), second = f.makeCard();
    const a = f.checks.confirm(first.button), b = f.checks.confirm(second.button);
    await Promise.resolve();
    release(confirmed);
    await Promise.all([a, b]);
    assert.equal(f.calls.length, 1);
    assert.equal(first.title.textContent, full);
    assert.equal(second.title.textContent, full);
    assert.equal(first.checkbox.checked, false);
    assert.equal(second.checkbox.checked, false);
});

test('불일치, 추가 내용 없음, 처리 제한은 확인 제목을 적용하지 않는다', async () => {
    for (const status of ['no_change', 'unverified', 'busy', 'failed']) {
        const f = fixture(async () => ({ status })), c = f.makeCard();
        await f.checks.confirm(c.button);
        assert.equal(c.content.hidden, true);
        assert.equal(f.checks.clippingTitle(c.clipButton, short), short);
        assert.equal(c.button.disabled, false);
        assert.ok(c.status.textContent);
    }
});

test('실패 후 수동으로 다시 시도할 수 있다', async () => {
    let attempts = 0;
    const f = fixture(async () => ++attempts === 1 ? { status: 'failed' } : confirmed), c = f.makeCard();
    await f.checks.confirm(c.button);
    assert.equal(c.label.textContent, '다시 시도');
    await f.checks.confirm(c.button);
    assert.equal(c.title.textContent, full);
    assert.equal(f.calls.length, 2);
});

test('브라우저 응답 제한 시간이 지나면 진행 표시를 해제하고 기존 제목을 유지한다', async () => {
    const f = fixture(options => new Promise((resolve, reject) => {
        options.signal.addEventListener('abort', () => reject(new DOMException('Stopped', 'AbortError')));
    })), c = f.makeCard();
    const task = f.checks.confirm(c.button);
    await Promise.resolve();
    for (const callback of f.timers.values()) callback();
    await task;
    assert.match(c.status.textContent, /초과/);
    assert.equal(c.button.disabled, false);
    assert.equal(c.button.busy, false);
    assert.equal(f.timers.size, 0);
    assert.equal(f.checks.clippingTitle(c.clipButton, short), short);
});

test('응답 전에 카드가 제거되면 결과를 표시하거나 제목을 적용하지 않는다', async () => {
    let release;
    const f = fixture(() => new Promise(resolve => { release = resolve; })), c = f.makeCard();
    const task = f.checks.confirm(c.button);
    await Promise.resolve(); c.card.isConnected = false;
    release(confirmed); await task;
    assert.equal(c.title.textContent, '');
    assert.equal(f.checks.clippingTitle(c.clipButton, short), short);
});

test('네이버 기사 출처를 구분하고 외부 문자열을 HTML로 삽입하지 않는다', async () => {
    const value = '<img src=x onerror=alert(1)>';
    const f = fixture(async () => ({ ...confirmed, title: value, source: 'naver', source_url: 'https://n.news.naver.com/mnews/article/001/123' }));
    const c = f.makeCard(); await f.checks.confirm(c.button);
    assert.equal(c.source.textContent, '네이버 기사');
    assert.equal(c.title.textContent, value);
    assert.equal(c.title.innerHTML, undefined);
});

test('유효하지 않은 출처 링크를 결과로 사용하지 않는다', async () => {
    const f = fixture(async () => ({ ...confirmed, source_url: 'javascript:alert(1)' })), c = f.makeCard();
    await f.checks.confirm(c.button);
    assert.equal(c.content.hidden, true);
    assert.equal(f.checks.clippingTitle(c.clipButton, short), short);
});

test('확인이 완료되어도 이미 작성된 클리핑은 덮어쓰지 않는다', async () => {
    const f = fixture(), c = f.makeCard(), writes = [];
    const document = { getElementById: () => null, addEventListener() {} };
    const window = {
        NewsArticleTitles: f.checks, NewsMotion: { success() {} },
        NewsUI: { read: () => '기존 편집 내용', write(key, text) { writes.push(text); return true; }, toast() {} },
        ClippingDocument: { emptyText: '', insertArticles(text, items) { return { added: 1, text: text + '\n' + items[0].title }; } }
    };
    vm.runInNewContext(fs.readFileSync(require.resolve('../static/js/clipping_service.js'), 'utf8'), { window, document });
    window.clipArticleFromData(short, 'https://example.com/a', '', '매체', '', '', c.clipButton, '기타');
    const original = writes.at(-1);
    await f.checks.confirm(c.button);
    c.checkbox.checked = true;
    assert.equal(writes.length, 1);
    assert.equal(writes.at(-1), original);
    window.clipArticleFromData(short, 'https://example.com/b', '', '매체', '', '', c.clipButton, '기타');
    assert.ok(writes.at(-1).endsWith(full));
});
