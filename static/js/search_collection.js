(function () {
    'use strict';
    const ui = window.NewsUI;
    function updateSelection(panel) {
        const boxes = [...panel.querySelectorAll('.news-select')];
        const count = boxes.filter(box => box.checked).length;
        const all = panel.querySelector('[data-select-all]');
        if (all) { all.checked = boxes.length > 0 && count === boxes.length; all.indeterminate = count > 0 && count < boxes.length; }
        const label = panel.querySelector('[data-selection-count]');
        if (label) label.textContent = `${count} / ${boxes.length}건 선택`;
        const button = panel.querySelector('[data-clip-selected]');
        if (button) button.disabled = !count;
    }
    async function collect(panel) {
        const since = panel.querySelector('[data-date-since]').value;
        const until = panel.querySelector('[data-date-until]').value;
        if (!since) { ui.toast('조회 시작일을 입력해주세요.'); return; }
        const form = new FormData();
        form.set('keyword', panel.dataset.keyword); form.set('since', since); form.set('until', until);
        const controller = window.NewsSearch.beginRequest(panel);
        const button = panel.querySelector('[data-collect-search]');
        button.disabled = true;
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
            if (controller === panel.searchController) panel.querySelector('[data-collect-search]').disabled = false;
        }
    }
    document.addEventListener('change', event => {
        const panel = event.target.closest('.tab-pane');
        if (!panel) return;
        if (event.target.matches('[data-select-all]')) {
            panel.querySelectorAll('.news-select').forEach(box => { box.checked = event.target.checked; });
        }
        if (event.target.matches('.news-select, [data-select-all]')) updateSelection(panel);
    });
    document.addEventListener('click', event => {
        const panel = event.target.closest('.tab-pane');
        if (!panel) return;
        if (event.target.closest('[data-collect-search]')) collect(panel);
        if (event.target.closest('[data-show-latest]')) window.NewsSearch.latest(panel);
        if (event.target.closest('[data-clip-selected]')) {
            const items = [...panel.querySelectorAll('.news-select:checked')].map(box => {
                const data = box.closest('.news-card').dataset;
                return { title: data.title, link: data.link, source: data.source, pubDate: data.pubdate, originalLink: data.originallink };
            });
            window.clipArticles(items, panel.querySelector('[data-bulk-category]').value);
        }
    });
    window.NewsSearchCollection = { updateSelection, collect };
}());
