(function (root) {
    'use strict';

    /** Confirmation is opt-in presentation; only an explicit checkbox changes future clipping. */
    function createTitleChecks(env) {
        const states = new WeakMap();
        const pending = new Map();
        const ui = env.NewsUI;
        const motion = env.NewsMotion;

        function request(button) {
            const key = button.dataset.titleKey;
            if (pending.has(key)) return pending.get(key);
            const promise = (async () => {
                const controller = new env.AbortController();
                const timer = env.setTimeout(() => controller.abort(), 4500);
                const form = new env.FormData();
                form.set('token', button.dataset.titleToken);
                try {
                    const response = await ui.request('/api/search/title-confirmation', {
                        method: 'POST', body: form, signal: controller.signal
                    });
                    return await response.json();
                } finally { env.clearTimeout(timer); }
            })();
            pending.set(key, promise);
            const cleanup = () => { if (pending.get(key) === promise) pending.delete(key); };
            promise.then(cleanup, cleanup);
            return promise;
        }

        function updateLabel(card, button, state) {
            const selected = state.phase === 'confirmed' && card.querySelector('[data-use-confirmed-title]').checked;
            button.querySelector('[data-title-button-label]').textContent = selected ? '확인 제목 사용' :
                state.phase === 'confirmed' ? '확인한 제목' : state.phase === 'failed' ? '다시 시도' : '확인 결과';
            if (state.phase === 'failed') button.removeAttribute('aria-expanded');
        }

        async function confirm(button) {
            const card = button.closest('.news-card');
            if (!card?.isConnected) return;
            const panel = card.querySelector('[data-title-result]');
            let state = states.get(card);
            if (state?.phase === 'loading') return;
            if (state && state.phase !== 'failed') {
                panel.hidden = !panel.hidden;
                button.setAttribute('aria-expanded', String(!panel.hidden));
                return;
            }
            state = { phase: 'loading', title: '' };
            states.set(card, state);
            panel.hidden = false;
            panel.querySelector('[data-confirmed-content]').hidden = true;
            const checkbox = panel.querySelector('[data-use-confirmed-title]');
            checkbox.checked = false;
            const status = panel.querySelector('[data-title-status]');
            status.textContent = '제목 확인 중';
            button.setAttribute('aria-expanded', 'true');
            button.querySelector('[data-title-button-label]').textContent = '확인 중';
            button.disabled = true;
            motion.setBusy(button, true);
            try {
                const data = await request(button);
                if (!card.isConnected) return;
                if (data.status === 'confirmed') {
                    const url = new URL(data.source_url);
                    const isNaver = ['news.naver.com', 'n.news.naver.com'].includes(url.hostname);
                    if (typeof data.title !== 'string' || !data.title || data.title.length > 400 ||
                        url.protocol !== 'https:' || url.username || url.password ||
                        data.source !== (isNaver ? 'naver' : 'original')) throw new Error('유효하지 않은 제목 확인 결과입니다.');
                    state.phase = 'confirmed'; state.title = data.title;
                    panel.querySelector('[data-confirmed-title]').textContent = data.title;
                    const source = panel.querySelector('[data-title-source]');
                    source.textContent = isNaver ? '네이버 기사' : '언론사 원문';
                    source.href = url.href;
                    panel.querySelector('[data-confirmed-content]').hidden = false;
                    status.textContent = '제목 확인 완료';
                } else if (data.status === 'no_change' || data.status === 'unverified') {
                    state.phase = data.status;
                    status.textContent = data.status === 'no_change' ? '추가 제목 없음' : '일치 확인 불가';
                } else {
                    state.phase = 'failed';
                    status.textContent = data.status === 'busy' ? '다른 제목을 확인 중입니다. 잠시 후 다시 시도해주세요.' :
                        '제목 확인 실패. 다시 시도해주세요.';
                }
            } catch (error) {
                if (!card.isConnected) return;
                state.phase = 'failed';
                status.textContent = error.name === 'AbortError' ? '제목 확인 시간이 초과되었습니다. 다시 시도해주세요.' :
                    error.message || '제목 확인 실패. 다시 시도해주세요.';
            } finally {
                motion.setBusy(button, false);
                button.disabled = false;
                if (card.isConnected) updateLabel(card, button, state);
            }
        }

        function clippingTitle(button, fallback) {
            const card = button?.closest?.('.news-card');
            const state = card && states.get(card);
            return state?.phase === 'confirmed' && card.querySelector('[data-use-confirmed-title]').checked ? state.title : fallback;
        }

        function selectionChanged(checkbox) {
            const card = checkbox.closest('.news-card');
            const state = states.get(card);
            if (state) updateLabel(card, card.querySelector('[data-title-confirm]'), state);
        }

        return { confirm, clippingTitle, selectionChanged };
    }

    if (typeof module !== 'undefined') module.exports = { createTitleChecks };
    else {
        root.NewsArticleTitles = createTitleChecks(root);
        root.document.addEventListener('click', event => {
            const button = event.target.closest('[data-title-confirm]');
            if (button) root.NewsArticleTitles.confirm(button);
        });
        root.document.addEventListener('change', event => {
            if (event.target.matches('[data-use-confirmed-title]')) root.NewsArticleTitles.selectionChanged(event.target);
        });
    }
}(typeof window !== 'undefined' ? window : {}));
