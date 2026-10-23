const { test } = require('node:test');
const assert = require('node:assert/strict');
const { createMotion, indicatorBounds } = require('../static/js/ui_motion.js');

function fixture() {
    const timers = new Map();
    const media = { matches: false, addEventListener() {} };
    const env = { matchMedia: () => media, document: { visibilityState: 'visible' },
        setTimeout: callback => { const id = Symbol(); timers.set(id, callback); return id; },
        clearTimeout: id => timers.delete(id) };
    const skeleton = { hidden: true };
    const label = { textContent: '' };
    const use = { setAttribute(name, value) { this[name] = value; } };
    const shell = { querySelector: selector => selector === '.search-skeleton' ? skeleton : selector === '[data-loading-label]' ? label : use };
    const panel = { isConnected: true, active: true, dataset: { searchState: 'loading' },
        classList: { contains: () => panel.active }, querySelector: () => shell, closest: () => panel };
    const motion = createMotion(env);
    return { motion, env, panel, skeleton, label, use, timers, media,
        flush() { const pending = [...timers.values()]; timers.clear(); pending.forEach(callback => callback()); } };
}

test('빠른 응답은 지연 로딩 그래픽을 취소하며 완료 후 다시 나타나지 않는다', () => {
    const f = fixture();
    f.motion.syncLoading(f.panel);
    assert.equal(f.skeleton.hidden, true);
    f.panel.dataset.searchState = 'ready';
    f.motion.endLoading(f.panel);
    f.flush();
    assert.equal(f.skeleton.hidden, true);
    assert.equal(f.timers.size, 0);
});
test('느린 검색만 스켈레톤을 표시하고 대기와 실제 검색을 구분한다', () => {
    const f = fixture();
    f.panel.dataset.searchState = 'queued';
    f.motion.syncLoading(f.panel); f.flush();
    assert.equal(f.skeleton.hidden, false);
    assert.equal(f.label.textContent, '검색 대기 중');
    assert.equal(f.use.href, '/static/icons.svg?v=motion-1#clock-3');
    f.panel.dataset.searchState = 'loading';
    f.motion.syncLoading(f.panel);
    assert.equal(f.label.textContent, '검색 중');
    assert.equal(f.use.href, '/static/icons.svg?v=motion-1#loader-circle');
});
test('비활성 탭과 닫힌 탭에는 로딩 타이머를 남기지 않는다', () => {
    const f = fixture();
    f.panel.active = false;
    f.motion.syncLoading(f.panel);
    assert.equal(f.timers.size, 0);
    f.panel.active = true; f.motion.syncLoading(f.panel);
    f.panel.isConnected = false; f.flush();
    assert.equal(f.skeleton.hidden, true);
});
test('모션 축소와 숨긴 문서에서는 이동 효과를 실행하지 않는다', () => {
    const f = fixture();
    const element = { isConnected: true, closest: () => f.panel, animate: () => { throw new Error('Unexpected animation'); } };
    f.media.matches = true;
    f.motion.reveal(element);
    assert.equal(f.motion.scrollBehavior(), 'auto');
    f.media.matches = false; f.env.document.visibilityState = 'hidden';
    f.motion.reveal(element);
});
test('빠르게 재실행하면 이전 애니메이션을 취소하고 취소 예외를 처리한다', async () => {
    const f = fixture();
    const animations = [];
    const element = { isConnected: true, closest: () => f.panel, animate() {
        let reject;
        const animation = { finished: new Promise((_, fail) => { reject = fail; }), cancelled: false,
            cancel() { this.cancelled = true; reject(new Error('cancelled')); } };
        animations.push(animation); return animation;
    } };
    f.motion.reveal(element); f.motion.reveal(element);
    assert.equal(animations[0].cancelled, true);
    f.motion.stop(element);
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(animations[1].cancelled, true);
});
test('탭 밑줄은 스크롤 영역 안으로 제한하고 화면 밖에서는 숨긴다', () => {
    assert.deepEqual(indicatorBounds({ left: 100, right: 250 }, { left: 120, right: 230 }, { left: 20 }), { x: 100, width: 110 });
    assert.equal(indicatorBounds({ left: 0, right: 40 }, { left: 100, right: 300 }, { left: 0 }), null);
});

function iconButton() {
    const use = { href: '/static/icons.svg?v=motion-1#copy', getAttribute(name) { return this[name]; }, setAttribute(name, value) { this[name] = value; } };
    const classes = new Set();
    const attributes = {};
    return { use, classes, attributes, querySelector: () => use,
        classList: { add: name => classes.add(name), remove: name => classes.delete(name) },
        setAttribute: (name, value) => { attributes[name] = value; }, removeAttribute: name => { delete attributes[name]; } };
}
test('진행 중 아이콘은 반복 설정해도 원래 아이콘으로 정확히 돌아간다', () => {
    const f = fixture(); const button = iconButton();
    f.motion.setBusy(button, true); f.motion.setBusy(button, true);
    assert.equal(button.use.href, '/static/icons.svg?v=motion-1#loader-circle');
    f.motion.setBusy(button, false);
    assert.equal(button.use.href, '/static/icons.svg?v=motion-1#copy');
    assert.equal(button.attributes['aria-busy'], undefined);
});
test('완료 피드백을 연속 실행해도 아이콘 복원 타이머는 하나만 남는다', () => {
    const f = fixture(); const button = iconButton();
    f.motion.success(button); f.motion.success(button);
    assert.equal(button.use.href, '/static/icons.svg?v=motion-1#check');
    assert.equal(f.timers.size, 1);
    f.flush();
    assert.equal(button.use.href, '/static/icons.svg?v=motion-1#copy');
    assert.equal(button.classes.size, 0);
});
test('진행 막대는 실제 전달값만 사용하고 범위를 벗어나지 않는다', () => {
    const f = fixture(); f.media.matches = true;
    const fill = { style: {} };
    f.motion.progress(fill, .4); assert.equal(fill.style.transform, 'scaleX(0.4)');
    f.motion.progress(fill, 2); assert.equal(fill.style.transform, 'scaleX(1)');
    f.motion.progress(fill, -1); assert.equal(fill.style.transform, 'scaleX(0)');
});
