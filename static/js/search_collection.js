(function () {
    'use strict';
    const ui = window.NewsUI;
    function updateCount(panel) {
        const label = panel.querySelector('[data-results-count]');
        if (label) label.textContent = `${panel.querySelectorAll('.news-card').length}건 표시`;
    }
    function initialize(panel) {
        const today = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Seoul' }).format(new Date());
        const yesterday = new Date(`${today}T00:00:00+09:00`);
        yesterday.setUTCDate(yesterday.getUTCDate() - 1);
        const since = panel.querySelector('[data-date-since]');
        const until = panel.querySelector('[data-date-until]');
        if (!since.value) since.value = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Seoul' }).format(yesterday);
        if (!until.value) until.value = today;
        updateCount(panel);
    }
    async function collect(panel) {
        const since = panel.querySelector('[data-date-since]').value;
        const until = panel.querySelector('[data-date-until]').value;
        if (!since) { ui.toast('조회 시작일을 입력해주세요.'); return; }
        if (until && since > until) { ui.toast('종료일은 시작일보다 빠를 수 없습니다.'); return; }
        const form = new FormData();
        form.set('keyword', panel.dataset.keyword); form.set('since', since); form.set('until', until);
        const controller = window.NewsSearch.beginRequest(panel);
        const button = panel.querySelector('[data-collect-search]');
        button.disabled = true;
        window.NewsMotion.setBusy(button, true);
        panel.querySelector('.search-results-list').setAttribute('aria-busy', 'true');
        const status = panel.querySelector('[data-collection-status]');
        status.textContent = '기간 내 기사를 조회하는 중...';
        status.classList.remove('status-warning');
        try {
            const response = await ui.request('/api/search/collect', { method: 'POST', body: form, signal: controller.signal });
            const data = await response.json();
            if (controller !== panel.searchController || !panel.isConnected) return;
            window.NewsSearch.replaceResults(panel, data.html);
            const nextStatus = panel.querySelector('[data-collection-status]');
            const parts = [`기간 내 기사 ${data.article_count}건`, data.complete ? '조회 완료' : '조회 한도 도달 · 기간 전체를 확인하지 못했습니다'];
            if (data.duplicate_count) parts.push(`동일 URL ${data.duplicate_count}건 정리`);
            if (data.invalid_date_count) parts.push(`발행일 확인 불가 ${data.invalid_date_count}건 제외`);
            nextStatus.textContent = parts.join(' · ');
            nextStatus.classList.toggle('status-warning', !data.complete || data.invalid_date_count > 0);
        } catch (error) {
            if (error.name !== 'AbortError' && controller === panel.searchController) {
                status.textContent = error.message;
                status.classList.add('status-warning');
                ui.toast(error.message);
                window.NewsSearch.resume(panel);
            }
        } finally {
            if (controller === panel.searchController) {
                panel.querySelector('.search-results-list')?.setAttribute('aria-busy', 'false');
                const current = panel.querySelector('[data-collect-search]');
                if (current) { current.disabled = false; window.NewsMotion.setBusy(current, false); }
            }
        }
    }
    document.addEventListener('submit', event => {
        if (!event.target.matches('.search-period-controls')) return;
        event.preventDefault();
        collect(event.target.closest('.tab-pane'));
    });
    document.addEventListener('click', event => {
        const panel = event.target.closest('.tab-pane');
        if (!panel) return;
        if (event.target.closest('[data-show-latest]')) window.NewsSearch.latest(panel);
    });
    window.NewsSearchCollection = { initialize, updateCount, collect };
}());
