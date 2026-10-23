(function () {
    'use strict';
    const ui = window.NewsUI;
    const observers = new Map();
    let counter = 0;
    let batchPromise = null;
    let batchRunning = false;
    let failedKeywords = [];
    let batchPanels = new Set();

    function setSearchState(panel, state) {
        panel.dataset.searchState = state;
        const button = document.querySelector(`.tabs-nav [data-tab="${panel.id}"]`);
        if (button) button.dataset.searchState = state;
        window.NewsSearchTabs?.update();
    }

    function disconnect(panel) {
        observers.get(panel.id)?.disconnect();
        observers.delete(panel.id);
    }
    function beginRequest(panel) {
        disconnect(panel);
        panel.searchController?.abort();
        panel.querySelectorAll('[data-search-refresh], [data-collect-search]').forEach(button => {
            button.disabled = false; button.removeAttribute('aria-busy');
        });
        panel.loadingMore = false;
        panel.searchController = new AbortController();
        return panel.searchController;
    }
    function applyLayout() {
        const grid = ui.read('navernews_search_layout') === 'grid';
        document.querySelectorAll('.search-results-list').forEach(list => list.classList.toggle('layout-grid', grid));
        document.querySelectorAll('.layout-toggle-btn').forEach(button => {
            const active = (button.dataset.layout === 'grid') === grid;
            button.classList.toggle('active', active); button.setAttribute('aria-pressed', String(active));
        });
    }
    window.setSearchLayout = layout => { ui.write('navernews_search_layout', layout); applyLayout(); };

    function switchTab(id) {
        document.querySelectorAll('.tab-pane').forEach(pane => pane.classList.toggle('active', pane.id === id));
        document.querySelectorAll('.tabs-nav-wrapper .tab-btn').forEach(button => button.classList.toggle('active', button.dataset.tab === id));
        if (id === 'clippings') window.loadClippingsTab();
        document.querySelector(`.tabs-nav [data-tab="${id}"]`)?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
        window.NewsSearchTabs?.update();
    }
    window.switchTab = switchTab;

    function replaceResults(panel, html) {
        disconnect(panel);
        panel.querySelector('.search-panel-content').innerHTML = html;
        const list = panel.querySelector('.search-results-list');
        panel.dataset.start = list.dataset.nextStart || '1';
        panel.dataset.hasMore = list.dataset.hasMore || 'false';
        panel.dataset.mode = list.dataset.mode || 'latest';
        window.syncVisibleWatchCheckboxes?.();
        applyLayout();
        window.NewsSearchCollection.initialize(panel);
        installSentinel(panel);
    }

    function sentinelMessage(panel, text, action) {
        const sentinel = panel.querySelector('.panel-sentinel');
        sentinel.replaceChildren();
        const label = document.createElement('span');
        label.textContent = text;
        sentinel.append(label);
        if (action) {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'btn-small';
            button.textContent = '더 불러오기';
            button.addEventListener('click', () => loadMore(panel));
            sentinel.append(button);
        }
    }

    function installSentinel(panel) {
        panel.querySelector('.panel-sentinel')?.remove();
        if (panel.dataset.mode !== 'latest') return;
        const sentinel = document.createElement('div');
        sentinel.className = 'panel-sentinel';
        panel.querySelector('.search-results-list').append(sentinel);
        if (panel.dataset.hasMore !== 'true') {
            const limit = panel.querySelector('.search-results-list').dataset.limitReached === 'true';
            sentinelMessage(panel, limit ? '조회 한도에 도달했습니다. 검색어를 구체화해 다시 조회해주세요.' : '더 이상 결과가 없습니다.');
            return;
        }
        sentinelMessage(panel, '', true);
        if (batchRunning) return;
        const observer = new IntersectionObserver(entries => {
            if (entries.some(entry => entry.isIntersecting)) loadMore(panel);
        }, { rootMargin: '300px' });
        observers.set(panel.id, observer);
        observer.observe(sentinel);
    }

    async function loadMore(panel) {
        if (panel.loadingMore || panel.dataset.hasMore !== 'true') return;
        panel.loadingMore = true;
        const controller = panel.searchController;
        const form = new FormData();
        form.set('keyword', panel.dataset.keyword);
        form.set('start', panel.dataset.start);
        sentinelMessage(panel, '결과를 불러오는 중...');
        try {
            const response = await ui.request('/search-results', { method: 'POST', body: form, signal: controller?.signal });
            const wrapper = document.createElement('div');
            wrapper.innerHTML = await response.text();
            if (controller !== panel.searchController || !panel.isConnected) return;
            const next = wrapper.querySelector('.search-results-list');
            const current = panel.querySelector('.search-results-list');
            const links = new Set([...current.querySelectorAll('.news-card')].map(card => card.dataset.link));
            next.querySelectorAll('.news-card').forEach(card => {
                if (!links.has(card.dataset.link)) { links.add(card.dataset.link); current.querySelector('.news-items').append(card); }
            });
            panel.dataset.start = next.dataset.nextStart;
            panel.dataset.hasMore = next.dataset.hasMore;
            current.dataset.limitReached = next.dataset.limitReached;
            disconnect(panel);
            window.NewsSearchCollection.updateCount(panel);
            installSentinel(panel);
        } catch (error) {
            if (error.name !== 'AbortError' && controller === panel.searchController) {
                disconnect(panel);
                sentinelMessage(panel, error.message, true);
            }
        } finally { if (controller === panel.searchController) panel.loadingMore = false; }
    }

    async function refreshLatest(panel) {
        const controller = beginRequest(panel);
        setSearchState(panel, 'loading');
        const loading = panel.querySelector('.search-panel-content > p[role="status"]');
        if (loading) loading.textContent = '검색 중...';
        const button = panel.querySelector('[data-search-refresh]');
        if (button) { button.disabled = true; button.setAttribute('aria-busy', 'true'); }
        const form = new FormData();
        form.set('keyword', panel.dataset.keyword);
        form.set('start', '1');
        form.set('refresh', 'true');
        try {
            const response = await ui.request('/search-results', { method: 'POST', body: form, signal: controller.signal });
            const html = await response.text();
            if (controller !== panel.searchController || !panel.isConnected) return 'cancelled';
            replaceResults(panel, html);
            setSearchState(panel, 'ready');
            return 'loaded';
        } catch (error) {
            if (error.name === 'AbortError' || controller !== panel.searchController) return 'cancelled';
            setSearchState(panel, 'failed');
            ui.toast(error.message);
            if (!panel.querySelector('.search-results-list')) {
                const content = panel.querySelector('.search-panel-content');
                const message = document.createElement('p');
                message.textContent = error.message;
                const retry = document.createElement('button');
                retry.type = 'button';
                retry.className = 'btn-small';
                retry.textContent = '다시 검색';
                retry.addEventListener('click', () => refreshLatest(panel));
                content.replaceChildren(message, retry);
            } else installSentinel(panel);
            return 'failed';
        } finally {
            const refresh = panel.querySelector('[data-search-refresh]');
            if (refresh && controller === panel.searchController) { refresh.disabled = false; refresh.removeAttribute('aria-busy'); }
        }
    }

    window.refreshSearchTab = id => {
        const panel = document.getElementById(id);
        if (!panel) return;
        return panel.dataset.mode === 'period' ? window.NewsSearchCollection.collect(panel) : refreshLatest(panel);
    };

    function rememberKeyword(keyword) {
        ui.write('navernews_recent_keywords', JSON.stringify([keyword, ...ui.readArray('navernews_recent_keywords').filter(item => item !== keyword)].slice(0, 10)));
        recentKeywords();
    }

    function ensureSearchPanel(keyword) {
        const existing = [...document.querySelectorAll('.tab-pane')].find(panel => panel.dataset.keyword === keyword);
        if (existing) return existing;
        const id = `search-${++counter}`;
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'tab-btn';
        button.dataset.tab = id;
        button.title = keyword;
        const label = document.createElement('span');
        label.className = 'tab-btn-label';
        label.textContent = keyword;
        const close = document.createElement('span');
        close.className = 'tab-btn-close';
        close.append(ui.icon('x'));
        close.setAttribute('role', 'button');
        close.setAttribute('tabindex', '0');
        close.setAttribute('aria-label', `${keyword} 탭 닫기`);
        const panel = document.createElement('div');
        panel.id = id;
        panel.className = 'tab-pane';
        panel.dataset.keyword = keyword;
        panel.innerHTML = '<div class="search-panel-shell"><div class="search-panel-content"><p role="status">검색 대기 중...</p></div></div>';
        function remove(event) {
            event.stopPropagation();
            disconnect(panel);
            panel.searchController?.abort();
            const wasActive = panel.classList.contains('active');
            panel.remove(); button.remove();
            if (wasActive) switchTab(document.querySelector('.tabs-nav .tab-btn:last-child')?.dataset.tab || 'homeTab');
            window.NewsSearchTabs?.update();
        }
        close.addEventListener('click', remove);
        close.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); remove(event); } });
        button.append(label, close);
        document.querySelector('.tabs-nav').append(button);
        document.querySelector('.tabs-content').append(panel);
        setSearchState(panel, 'queued');
        return panel;
    }

    async function loadInitial(panel) {
        if (!panel.isConnected) return 'cancelled';
        if (panel.initialSearch) return panel.initialSearch;
        panel.initialSearch = refreshLatest(panel);
        try { return await panel.initialSearch; }
        finally { panel.initialSearch = null; }
    }

    async function openSearch(keyword, activate = true) {
        keyword = keyword.trim();
        if (!keyword || keyword.length > 300) { ui.toast('검색어는 1~300자로 입력해주세요.'); return 'failed'; }
        rememberKeyword(keyword);
        const panel = ensureSearchPanel(keyword);
        const id = panel.id;
        if (activate) switchTab(id);
        if (batchRunning && batchPanels.has(panel) && panel.dataset.searchState === 'queued') return 'queued';
        if (panel.initialSearch || ['queued', 'failed'].includes(panel.dataset.searchState)) return loadInitial(panel);
        return 'reused';
    }

    function recentKeywords() {
        const container = document.getElementById('recentKeywords');
        container.replaceChildren();
        const header = document.createElement('div');
        header.className = 'recent-keywords-header';
        header.textContent = '최근 검색어';
        container.append(header);
        ui.readArray('navernews_recent_keywords').forEach(keyword => {
            const row = document.createElement('div');
            row.className = 'recent-keyword-item';
            const button = document.createElement('button');
            button.type = 'button'; button.textContent = keyword;
            button.addEventListener('click', () => {
                container.classList.remove('show'); openSearch(keyword);
            });
            const remove = document.createElement('button');
            remove.type = 'button'; remove.className = 'icon-button'; remove.append(ui.icon('x'));
            remove.setAttribute('aria-label', `${keyword} 최근 검색어 삭제`); remove.title = '최근 검색어 삭제';
            remove.addEventListener('click', () => { ui.write('navernews_recent_keywords', JSON.stringify(ui.readArray('navernews_recent_keywords').filter(item => item !== keyword))); recentKeywords(); });
            row.append(button, remove); container.append(row);
        });
        const home = document.getElementById('homeRecentKeywords');
        home.replaceChildren();
        const recent = ui.readArray('navernews_recent_keywords');
        if (!recent.length) {
            const empty = document.createElement('li'); empty.className = 'empty-msg';
            empty.textContent = '최근 검색 내역이 없습니다.'; home.append(empty);
        }
        recent.forEach(keyword => {
            const row = document.createElement('li');
            const button = document.createElement('button'); button.type = 'button';
            const label = document.createElement('span'); label.textContent = keyword;
            button.append(label, ui.icon('arrow-up-right'));
            button.addEventListener('click', () => openSearch(keyword));
            row.append(button); home.append(row);
        });
    }

    window.handleSearch = async function () {
        const input = document.getElementById('keyword');
        const base = input.value.trim();
        if (!base) { ui.toast('검색어를 입력하세요.'); return; }
        let keyword = base;
        const include = document.getElementById('advInclude').value.trim();
        const exclude = document.getElementById('advExclude').value.trim();
        if (include) keyword += ` +"${include}"`;
        if (exclude) keyword += exclude.split(/\s+/).map(term => ` -${term}`).join('');
        document.getElementById('recentKeywords').classList.remove('show');
        document.getElementById('advancedSearchPanel').classList.remove('show');
        document.getElementById('advancedSearchToggleBtn').setAttribute('aria-expanded', 'false');
        input.value = '';
        await openSearch(keyword);
    };

    function updateTheme() {
        const dark = document.body.classList.contains('dark-mode');
        const label = dark ? '라이트 모드로 전환' : '다크 모드로 전환';
        const button = document.querySelector('.theme-btn');
        button.setAttribute('aria-label', label); button.title = label;
        button.replaceChildren(ui.icon(dark ? 'sun' : 'moon'));
        document.querySelector('.toastui-editor-defaultUI')?.classList.toggle('toastui-editor-dark', dark);
    }
    window.toggleTheme = () => { document.body.classList.toggle('dark-mode'); ui.write('theme', document.body.classList.contains('dark-mode') ? 'dark' : 'light'); updateTheme(); };
    function updateBatchStatus(state) {
        const bar = document.getElementById('batchSearchStatus');
        bar.hidden = false;
        const done = state.completed === state.total;
        const parts = [`검색 ${state.completed} / ${state.total} 처리${done ? ' 완료' : ' 중'}`];
        if (state.reused) parts.push(`기존 탭 ${state.reused}개 재사용`);
        if (state.failed.length) parts.push(`실패 ${state.failed.length}개`);
        if (state.cancelled) parts.push(`닫힌 탭 ${state.cancelled}개 제외`);
        document.getElementById('batchSearchMessage').textContent = parts.join(' · ');
        const progress = document.getElementById('batchSearchProgress');
        progress.max = Math.max(1, state.total); progress.value = state.completed; progress.hidden = done;
        const retry = document.getElementById('retryFailedSearchesBtn');
        retry.hidden = !done || !state.failed.length;
        retry.querySelector('span').textContent = `실패 ${state.failed.length}개 재시도`;
        document.getElementById('dismissBatchStatusBtn').hidden = !done;
    }

    /** Share one running batch so repeated clicks cannot create overlapping request queues. */
    function openMany(keywords) {
        if (batchPromise) return batchPromise;
        const unique = window.NewsSearchBatch.normalizeKeywords(keywords);
        if (!unique.length) return Promise.resolve();
        batchRunning = true;
        document.dispatchEvent(new CustomEvent('news:batch-state', { detail: { running: true } }));
        const panels = unique.map(keyword => { rememberKeyword(keyword); return ensureSearchPanel(keyword); });
        batchPanels = new Set(panels);
        switchTab(panels[0].id);
        batchPromise = (async () => {
            try {
                const result = await window.NewsSearchBatch.runBatch(unique, async (_, index) => {
                    const panel = panels[index];
                    if (!panel.isConnected) return 'cancelled';
                    if (panel.dataset.searchState === 'ready') return 'reused';
                    return loadInitial(panel);
                }, updateBatchStatus);
                failedKeywords = result.failed;
                return result;
            } finally {
                batchPromise = null; batchRunning = false;
                batchPanels.clear();
                document.dispatchEvent(new CustomEvent('news:batch-state', { detail: { running: false } }));
                document.querySelectorAll('.tab-pane[data-keyword]').forEach(panel => {
                    if (panel.querySelector('.search-results-list') && panel.dataset.mode === 'latest') installSentinel(panel);
                });
            }
        })();
        return batchPromise;
    }
    window.NewsSearch = { beginRequest, replaceResults, disconnect, openSearch, openMany, latest: refreshLatest, resume: installSentinel };

    document.addEventListener('DOMContentLoaded', () => {
        document.body.classList.toggle('dark-mode', ui.read('theme') === 'dark');
        updateTheme();
        document.getElementById('searchBtn').addEventListener('click', window.handleSearch);
        for (const id of ['keyword', 'advInclude', 'advExclude']) {
            document.getElementById(id).addEventListener('keydown', event => { if (event.key === 'Enter' && !event.isComposing) window.handleSearch(); });
        }
        document.getElementById('keyword').addEventListener('focus', () => {
            recentKeywords();
            if (ui.readArray('navernews_recent_keywords').length) document.getElementById('recentKeywords').classList.add('show');
        });
        recentKeywords();
        document.getElementById('retryFailedSearchesBtn').addEventListener('click', () => openMany(failedKeywords));
        document.getElementById('dismissBatchStatusBtn').addEventListener('click', () => { document.getElementById('batchSearchStatus').hidden = true; });
        const filterButton = document.getElementById('advancedSearchToggleBtn');
        filterButton.addEventListener('click', () => {
            const expanded = document.getElementById('advancedSearchPanel').classList.toggle('show');
            filterButton.setAttribute('aria-expanded', String(expanded));
        });
        document.querySelector('.tabs-nav-wrapper').addEventListener('click', event => {
            const button = event.target.closest('button[data-tab]');
            if (button) switchTab(button.dataset.tab);
        });
        document.addEventListener('click', event => {
            const refresh = event.target.closest('[data-search-refresh]');
            if (refresh) window.refreshSearchTab(refresh.closest('.tab-pane').id);
            if (!event.target.closest('.search-box')) {
                document.getElementById('recentKeywords').classList.remove('show');
                document.getElementById('advancedSearchPanel').classList.remove('show');
                filterButton.setAttribute('aria-expanded', 'false');
            }
        });
        document.getElementById('scrollTopBtn').addEventListener('click', () => window.scrollTo({ top: 0, behavior: 'smooth' }));
        document.getElementById('scrollBottomBtn').addEventListener('click', () => window.scrollTo({ top: document.documentElement.scrollHeight, behavior: 'smooth' }));
        window.addEventListener('scroll', () => document.getElementById('scrollControls').classList.toggle('show', window.scrollY > 300), { passive: true });
    });
}());
