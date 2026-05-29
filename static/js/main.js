/**
 * main.js
 * 
 * Core logic for the Naver News Web Application.
 * Handles search, tab management, infinite scrolling, and clipping (text-based).
 */

// ==============================================================================
// 1. CONFIGURATION & GLOBALS
// ==============================================================================

const RECENT_KEYWORDS_KEY = 'navernews_recent_keywords';
const SEARCH_LAYOUT_KEY = 'navernews_search_layout';
// CLIPPING_TEXT_KEY is now managed globally or in clipping_service.js

// Global state
let searchTabCounter = 0;
const panelObservers = new Map(); // Stores IntersectionObservers for infinite scroll
// Get or Create Persistent Client ID
window.sseClientId = localStorage.getItem('navernews_client_id') || 
                     'client_' + Math.random().toString(36).substr(2, 9) + Date.now().toString(36);
localStorage.setItem('navernews_client_id', window.sseClientId);
window.keywordWatchSet = new Set(JSON.parse(localStorage.getItem('watchedKeywords') || '[]'));


// ==============================================================================
// 2. UTILITY FUNCTIONS
// ==============================================================================

/**
 * Escapes HTML characters to prevent XSS.
 */
function escapeHtml(s) {
    return String(s || '').replace(/[&<>"']/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
}

/**
 * Escapes attribute values.
 */
function escapeAttr(s) {
    return String(s || '').replace(/[&<>"']/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
}

function escapeCssValue(value) {
    if (window.CSS && typeof window.CSS.escape === 'function') {
        return window.CSS.escape(String(value || ''));
    }
    return String(value || '').replace(/\\/g, '\\\\').replace(/"/g, '\\"');
}

/**
 * Shows a toast message.
 */
function showToast(message) {
    const container = document.getElementById('toastContainer');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.textContent = message;

    container.appendChild(toast);

    // Trigger animation
    setTimeout(() => toast.classList.add('show'), 10);

    // Remove after 3 seconds
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}
// Expose to window for inline calls if necessary
window.showToast = showToast;

function getWatchedKeywords() {
    return Array.from(window.keywordWatchSet || []);
}

function persistWatchedKeywords() {
    localStorage.setItem('watchedKeywords', JSON.stringify(getWatchedKeywords()));
}

function syncVisibleWatchCheckboxes(keyword = null) {
    const selector = keyword
        ? `.watch-checkbox[data-keyword="${escapeCssValue(keyword)}"]`
        : '.watch-checkbox';

    document.querySelectorAll(selector).forEach(checkbox => {
        if (window.keywordWatchSet) {
            checkbox.checked = window.keywordWatchSet.has(checkbox.dataset.keyword);
        }
    });
}

function setWatchStateLocally(keyword, isChecked) {
    if (!window.keywordWatchSet) {
        window.keywordWatchSet = new Set();
    }

    if (isChecked) {
        window.keywordWatchSet.add(keyword);
    } else {
        window.keywordWatchSet.delete(keyword);
    }

    persistWatchedKeywords();
    renderActiveAlerts();
    syncVisibleWatchCheckboxes(keyword);
}

window.toggleKeywordWatch = async function(el) {
    const keyword = el.dataset.keyword;
    if (!keyword) return;

    const isChecked = el.checked;
    const clientId = window.sseClientId;

    setWatchStateLocally(keyword, isChecked);
    showToast(isChecked
        ? `[${keyword}] 실시간 알림을 시작합니다.`
        : `[${keyword}] 실시간 알림을 중단합니다.`
    );

    const url = isChecked ? '/api/watch' : '/api/unwatch';
    const formData = new FormData();
    formData.append('keyword', keyword);
    formData.append('client_id', clientId);

    try {
        const resp = await fetch(url, { method: 'POST', body: formData });
        if (!resp.ok || resp.redirected) {
            throw new Error(`watch sync failed: ${resp.status}`);
        }
    } catch (e) {
        console.error('Watch toggle error:', e);
        setWatchStateLocally(keyword, !isChecked);
        showToast('알림 서버 동기화에 실패해 이전 상태로 되돌렸습니다.');
    }
};

/**
 * Renders the active alerts list in the Clippings tab.
 */
function renderActiveAlerts() {
    const listContainer = document.getElementById('activeAlertList');
    if (!listContainer) return;
    const summaryBadge = document.getElementById('alertSummaryBadge');

    if (!window.keywordWatchSet || window.keywordWatchSet.size === 0) {
        listContainer.innerHTML = '<p class="empty-msg">활성화된 알림이 없습니다.</p>';
        if (summaryBadge) summaryBadge.textContent = '0개 활성';
        return;
    }

    listContainer.innerHTML = '';
    if (summaryBadge) summaryBadge.textContent = `${window.keywordWatchSet.size}개 활성`;
    window.keywordWatchSet.forEach(keyword => {
        const item = document.createElement('div');
        item.className = 'alert-item';
        item.innerHTML = `
            <span>${escapeHtml(keyword)}</span>
            <button class="btn-remove-alert" onclick="removeAlertFromManager('${escapeAttr(keyword)}')" title="알림 끄기">×</button>
        `;
        listContainer.appendChild(item);
    });
}

/**
 * Removes an alert from the central manager.
 */
window.removeAlertFromManager = async function(keyword) {
    if (!confirm(`[${keyword}] 알림을 중단하시겠습니까?`)) return;

    setWatchStateLocally(keyword, false);

    // Sync with server (Absolute Sync)
    syncAlertsWithServer();

    showToast(`[${keyword}] 알림이 중단되었습니다.`);
};

/**
 * Clears all active alerts.
 */
async function clearAllAlerts() {
    if (window.keywordWatchSet.size === 0) return;
    if (!confirm('정말로 모든 실시간 알림을 초기화하시겠습니까?')) return;

    window.keywordWatchSet.clear();
    persistWatchedKeywords();

    // Sync with server (Absolute Sync)
    syncAlertsWithServer();

    // Update UI
    renderActiveAlerts();
    syncVisibleWatchCheckboxes();

    showToast('모든 실시간 알림이 초기화되었습니다.');
}
window.clearAllAlerts = clearAllAlerts;

/**
 * Authoritative sync with server
 */
function syncAlertsWithServer() {
    const keywords = getWatchedKeywords();
    fetch('/api/sync-watch', { 
        method: 'POST', 
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            client_id: window.sseClientId,
            keywords: keywords
        })
    }).catch(e => {
        console.error('Sync error:', e);
        showToast('알림 서버 동기화에 실패했습니다. 새로고침 후 다시 확인해주세요.');
    });
}
window.renderActiveAlerts = renderActiveAlerts;



// ==============================================================================
// 3. DATA MANAGEMENT (RECENT KEYWORDS)
// ==============================================================================

function getRecentKeywords() {
    const data = localStorage.getItem(RECENT_KEYWORDS_KEY);
    return data ? JSON.parse(data) : [];
}

function saveRecentKeyword(keyword) {
    if (!keyword) return;
    let keywords = getRecentKeywords();
    // Remove duplicate if exists, then add to front
    keywords = keywords.filter(k => k !== keyword);
    keywords.unshift(keyword);
    // Keep only last 10
    if (keywords.length > 10) keywords.pop();
    localStorage.setItem(RECENT_KEYWORDS_KEY, JSON.stringify(keywords));
}

function deleteRecentKeyword(keyword, event) {
    if (event) event.stopPropagation();
    let keywords = getRecentKeywords();
    keywords = keywords.filter(k => k !== keyword);
    localStorage.setItem(RECENT_KEYWORDS_KEY, JSON.stringify(keywords));
    renderRecentKeywords();
}
// Expose for onclick events in HTML
window.deleteRecentKeyword = deleteRecentKeyword;

function renderRecentKeywords() {
    const container = document.getElementById('recentKeywords');
    if (!container) return;

    const keywords = getRecentKeywords();
    if (keywords.length === 0) {
        container.innerHTML = `
            <div class="recent-keywords-header">
                <span>최근 검색어</span>
            </div>
            <div class="recent-keywords-empty">최근 검색어가 없습니다</div>
        `;
        return;
    }

    let html = `
        <div class="recent-keywords-header">
            <span>최근 검색어</span>
            <button class="clear-all-btn" onclick="clearAllRecentKeywords(event)">모두 지우기</button>
        </div>
    `;
    keywords.forEach(kw => {
        html += `
            <div class="recent-keyword-item" onclick="handleRecentKeywordClick('${escapeAttr(kw)}')">
                <span>${escapeHtml(kw)}</span>
                <span class="delete-btn" onclick="deleteRecentKeyword('${escapeAttr(kw)}', event)">×</span>
            </div>
        `;
    });
    container.innerHTML = html;
}

function handleRecentKeywordClick(keyword) {
    const input = document.getElementById('keyword');
    if (input) {
        input.value = keyword;
        handleSearch();
        const el = document.getElementById('recentKeywords');
        if (el) el.classList.remove('show');
    }
}
window.handleRecentKeywordClick = handleRecentKeywordClick;

function clearAllRecentKeywords(event) {
    if (event) event.stopPropagation();

    if (!confirm('모든 최근 검색어를 삭제하시겠습니까?')) {
        return;
    }

    localStorage.removeItem(RECENT_KEYWORDS_KEY);

    const el = document.getElementById('recentKeywords');
    if (el) el.classList.remove('show');
}
window.clearAllRecentKeywords = clearAllRecentKeywords;


// ==============================================================================
// 4. UI COMPONENTS & TAB MANAGEMENT
// ==============================================================================

function getSkeletonHTML() {
    return `
    <div class="skeleton-card">
        <div class="skeleton skeleton-title"></div>
        <div class="skeleton skeleton-text"></div>
        <div class="skeleton skeleton-text short"></div>
    </div>
    <div class="skeleton-card">
        <div class="skeleton skeleton-title"></div>
        <div class="skeleton skeleton-text"></div>
        <div class="skeleton skeleton-text short"></div>
    </div>
    `;
}

/**
 * Returns the inner HTML for a sentinel (loading indicator).
 */
function getSentinelHTML(text = '결과를 불러오는 중...') {
    return `
        <div class="spinner"></div>
        <span>${text}</span>
    `;
}

function getSearchLayout() {
    const saved = localStorage.getItem(SEARCH_LAYOUT_KEY);
    return saved === 'grid' ? 'grid' : 'list';
}

function applySearchLayout() {
    const layout = getSearchLayout();
    document.querySelectorAll('.search-results-list').forEach((list) => {
        list.classList.toggle('layout-grid', layout === 'grid');
    });
    document.querySelectorAll('.layout-toggle-btn').forEach((button) => {
        button.classList.toggle('active', button.dataset.layout === layout);
    });
}

window.setSearchLayout = function(layout) {
    const nextLayout = layout === 'grid' ? 'grid' : 'list';
    localStorage.setItem(SEARCH_LAYOUT_KEY, nextLayout);
    applySearchLayout();
};

function extractSearchContent(html, stripToolbar = false) {
    const wrapper = document.createElement('div');
    wrapper.innerHTML = html;
    if (stripToolbar) {
        const toolbar = wrapper.querySelector('.results-toolbar');
        if (toolbar) toolbar.remove();
    }
    return wrapper.innerHTML;
}

function syncSearchPanelControls(panel) {
    const checkbox = panel.querySelector('.watch-checkbox');
    if (checkbox && window.keywordWatchSet) {
        checkbox.checked = window.keywordWatchSet.has(checkbox.dataset.keyword);
    }
}

function resetPanelSentinel(panel) {
    const contentArea = panel.querySelector('.search-panel-content');
    if (!contentArea) return;

    const existingSentinel = contentArea.querySelector('.panel-sentinel');
    if (existingSentinel) existingSentinel.remove();

    const sentinel = document.createElement('div');
    sentinel.className = 'panel-sentinel';
    sentinel.innerHTML = getSentinelHTML();
    contentArea.appendChild(sentinel);
}

function renderSearchResultsIntoPanel(panel, html, nextStart = 21) {
    const contentArea = panel.querySelector('.search-panel-content');
    if (!contentArea) return;

    contentArea.innerHTML = extractSearchContent(html);
    panel.dataset.start = String(nextStart);
    syncSearchPanelControls(panel);
    resetPanelSentinel(panel);
    setupInfiniteScrollForPanel(panel);
    applySearchLayout();
}

/**
 * Creates a new search result tab.
 */
function createSearchTab(keyword, htmlContent, start = 1, activate = true) {
    const id = 'search-' + (++searchTabCounter) + '-' + Date.now().toString(36);

    // 1. Create Tab Button
    const btn = document.createElement('button');
    btn.className = 'tab-btn';
    btn.dataset.tab = id;
    btn.title = keyword;

    const label = document.createElement('span');
    label.className = 'tab-btn-label';
    label.textContent = keyword;

    const close = document.createElement('span');
    close.className = 'tab-btn-close';
    close.textContent = ' ×';
    close.onclick = (e) => {
        e.stopPropagation();
        removeSearchTab(id);
    };
    btn.appendChild(label);
    btn.appendChild(close);

    const navContainer = document.querySelector('.tabs-nav');
    if (navContainer) {
        navContainer.appendChild(btn);
    }

    // 2. Create Tab Panel
    const panel = document.createElement('div');
    panel.className = 'tab-pane';
    panel.id = id;
    panel.dataset.keyword = keyword;
    panel.dataset.start = String(start);

    panel.innerHTML = `
        <div class="search-panel-shell">
            <div class="search-panel-content">${htmlContent || getSkeletonHTML()}</div>
        </div>
    `;

    // Add Sentinel for Infinite Scroll
    const sentinel = document.createElement('div');
    sentinel.className = 'panel-sentinel';
    sentinel.innerHTML = getSentinelHTML();

    const innerDiv = panel.querySelector('.search-panel-content');
    if (innerDiv) innerDiv.appendChild(sentinel);

    document.querySelector('.tabs-content').appendChild(panel);

    // Activate and Setup
    if (activate) {
        switchTab(id);
    }
    setupInfiniteScrollForPanel(panel);
    applySearchLayout();
    return id;
}

function removeSearchTab(id) {
    const btn = document.querySelector(`.tabs-nav [data-tab="${id}"]`);
    const panel = document.getElementById(id);

    if (btn) btn.remove();
    if (panel) {
        // Handle unwatch if it was being watched
        const checkbox = panel.querySelector('.watch-checkbox');
        if (checkbox && checkbox.checked) {
            const keyword = checkbox.dataset.keyword;
            const formData = new FormData();
            formData.append('keyword', keyword);
            formData.append('client_id', window.sseClientId);
            fetch('/api/unwatch', { method: 'POST', body: formData }).catch(() => {});
            
            if (window.keywordWatchSet) window.keywordWatchSet.delete(keyword);
            localStorage.setItem('watchedKeywords', JSON.stringify(Array.from(window.keywordWatchSet || [])));
        }

        // Clean up observer
        if (panelObservers.has(id)) {
            try { panelObservers.get(id).disconnect(); } catch (e) { }
            panelObservers.delete(id);
        }
        panel.remove();
    }

    // Switch to the last remaining tab
    const remainingTabs = document.querySelectorAll('.tabs-nav .tab-btn');
    const lastSearchTab = Array.from(remainingTabs).filter(t => t.dataset.tab && t.dataset.tab.startsWith('search-')).pop();

    if (lastSearchTab) {
        switchTab(lastSearchTab.dataset.tab);
    } else {
        switchTab('homeTab');
    }
}

async function refreshSearchTab(id) {
    const panel = document.getElementById(id);
    if (!panel) return;

    const keyword = panel.dataset.keyword;
    const contentArea = panel.querySelector('.search-panel-content');
    const previousHtml = contentArea ? contentArea.innerHTML : '';
    const refreshBtn = panel.querySelector('[data-search-refresh]');

    if (contentArea) {
        contentArea.innerHTML = getSkeletonHTML();
        showToast(`'${keyword}' 검색 결과를 새로고침하는 중...`);
    }
    if (refreshBtn) {
        refreshBtn.disabled = true;
        refreshBtn.textContent = '새로고침 중';
    }

    const fd = new FormData();
    fd.append('keyword', keyword);
    fd.append('start', 1);
    fd.append('refresh', 'true');

    try {
        const resp = await fetch('/search-results', { method: 'POST', body: fd });
        if (resp.redirected || resp.status === 401) {
            throw new Error('인증이 만료되었습니다. 다시 로그인한 뒤 새로고침해주세요.');
        }
        if (!resp.ok) {
            throw new Error(`새로고침 실패: 서버 오류 ${resp.status}`);
        }
        const html = await resp.text();
        if (!html || !html.includes('search-results-list')) {
            throw new Error('새 검색 결과 화면을 불러오지 못했습니다.');
        }

        renderSearchResultsIntoPanel(panel, html, 21);
        showToast(`'${keyword}' 검색 결과를 새로고침 완료했습니다.`);
    } catch (e) {
        console.error('새로고침 오류:', e);
        showToast(e.message || '새로고침 중 네트워크 오류가 발생했습니다.');
        if (contentArea && previousHtml) {
            contentArea.innerHTML = previousHtml;
            resetPanelSentinel(panel);
            syncSearchPanelControls(panel);
            setupInfiniteScrollForPanel(panel);
            applySearchLayout();
        }
    } finally {
        const nextRefreshBtn = panel.querySelector('[data-search-refresh]');
        if (nextRefreshBtn) {
            nextRefreshBtn.disabled = false;
            nextRefreshBtn.textContent = '새로고침';
        }
    }
}
window.refreshSearchTab = refreshSearchTab;

function switchTab(tabId) {
    if (!tabId) return;

    // Deactivate all
    document.querySelectorAll('.tabs-nav .tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));

    // Activate target
    const tabBtn = document.querySelector(`.tabs-nav [data-tab="${tabId}"]`);
    const panel = document.getElementById(tabId);

    if (tabBtn) tabBtn.classList.add('active');
    if (panel) {
        panel.classList.add('active');
        // Sync toggle state from registry
        const checkbox = panel.querySelector('.watch-checkbox');
        if (checkbox && window.keywordWatchSet) {
            checkbox.checked = window.keywordWatchSet.has(checkbox.dataset.keyword);
        }
    }

    // Toggle Initial Message
    const hasSearchResults = !!document.querySelector('.tabs-nav button[data-tab^="search-"]');
    const initialMessage = document.getElementById('initialSearchMessage');
    if (initialMessage) {
        initialMessage.style.display = hasSearchResults ? 'none' : 'block';
    }
}

let candidateCategories = ['위원회 관련', '방송·통신 관련', '유관기관 관련', '기타'];
let candidateCache = [];
let candidateKeywords = [];
let candidateCurrentStatus = 'pending';
const candidateStatusLabels = {
    pending: '대기 후보',
    rejected: '제외 이력',
    accepted: '반영 이력'
};

async function loadCandidatesTab() {
    const candidatesPane = document.getElementById('candidates');
    if (!candidatesPane) return;

    let innerContainer = candidatesPane.querySelector('.tab-content-inner');
    if (!innerContainer) {
        innerContainer = document.createElement('div');
        innerContainer.className = 'tab-content-inner';
        candidatesPane.appendChild(innerContainer);
    }

    const hasContent = innerContainer.querySelector('#candidateList');
    if (!hasContent) {
        innerContainer.innerHTML = '<div class="loading-state">학습 화면을 불러오는 중...</div>';
        try {
            const resp = await fetch('/candidates-tab');
            innerContainer.innerHTML = await resp.text();
            setupCandidateActions();
            if (typeof window.initializeLearningPanel === 'function') {
                window.initializeLearningPanel();
            }
        } catch (e) {
            console.error('Candidate tab load failed:', e);
            innerContainer.innerHTML = '<div class="error-state">학습 화면을 불러오지 못했습니다.</div>';
            return;
        }
    } else if (typeof window.refreshLearningStatus === 'function') {
        window.refreshLearningStatus();
    }

    await refreshCandidates();
}
window.loadCandidatesTab = loadCandidatesTab;

function setupCandidateActions() {
    const runBtn = document.getElementById('runCandidatesBtn');
    if (runBtn) {
        runBtn.addEventListener('click', runCandidateCollection);
    }

    const clearPendingBtn = document.getElementById('clearPendingCandidatesBtn');
    if (clearPendingBtn) {
        clearPendingBtn.addEventListener('click', clearPendingCandidates);
    }

    const addKeywordBtn = document.getElementById('addCandidateKeywordBtn');
    const keywordInput = document.getElementById('candidateKeywordInput');
    if (addKeywordBtn && keywordInput) {
        addKeywordBtn.addEventListener('click', () => {
            addCandidateKeyword(keywordInput.value);
        });
        keywordInput.addEventListener('keypress', (event) => {
            if (event.key === 'Enter') addCandidateKeyword(keywordInput.value);
        });
    }

    const addOpenTabsBtn = document.getElementById('addOpenSearchTabsBtn');
    if (addOpenTabsBtn) {
        addOpenTabsBtn.addEventListener('click', addOpenSearchTabKeywords);
    }

    const statusTabs = document.querySelector('.candidate-status-tabs');
    if (statusTabs) {
        statusTabs.addEventListener('click', async (event) => {
            const tab = event.target.closest('[data-candidate-status]');
            if (!tab) return;
            candidateCurrentStatus = tab.dataset.candidateStatus || 'pending';
            await refreshCandidates();
        });
    }

    const keywordList = document.getElementById('candidateKeywordList');
    if (keywordList) {
        keywordList.addEventListener('click', async (event) => {
            const removeBtn = event.target.closest('[data-candidate-keyword-remove]');
            if (!removeBtn) return;
            await removeCandidateKeyword(removeBtn.dataset.keyword);
        });
    }

    const list = document.getElementById('candidateList');
    if (!list) return;

    list.addEventListener('click', async (event) => {
        const acceptBtn = event.target.closest('[data-candidate-accept]');
        const rejectBtn = event.target.closest('[data-candidate-reject]');
        const restoreBtn = event.target.closest('[data-candidate-restore]');
        const deleteBtn = event.target.closest('[data-candidate-delete]');
        const openBtn = event.target.closest('[data-candidate-open]');
        const card = event.target.closest('.candidate-card');
        if (!card) return;

        const candidateId = Number(card.dataset.candidateId);
        const item = candidateCache.find((candidate) => candidate.id === candidateId);
        if (!item) return;

        if (openBtn) {
            window.open(item.original_link || item.link, '_blank', 'noopener,noreferrer');
            return;
        }

        if (rejectBtn) {
            await rejectCandidate(candidateId);
            return;
        }

        if (restoreBtn) {
            await restoreCandidate(candidateId);
            return;
        }

        if (deleteBtn) {
            await deleteCandidate(candidateId);
            return;
        }

        if (acceptBtn) {
            const select = card.querySelector('.candidate-category-select');
            const category = select ? select.value : item.suggested_category;
            await acceptCandidate(item, category, acceptBtn);
        }
    });
}

async function runCandidateCollection() {
    const status = document.getElementById('candidateStatus');
    const btn = document.getElementById('runCandidatesBtn');
    if (!candidateKeywords.length) {
        if (status) status.textContent = '후보 수집 검색어를 먼저 추가하세요.';
        showToast('후보 수집 검색어가 필요합니다.');
        return;
    }

    if (status) status.textContent = '후보를 수집하는 중입니다...';
    if (btn) btn.disabled = true;

    try {
        const sinceSelect = document.getElementById('sinceOverride');
        const fd = new FormData();
        if (sinceSelect && sinceSelect.value) {
            fd.append('since', sinceSelect.value);
        }

        const resp = await fetch('/api/clipping-candidates/run', { method: 'POST', body: fd });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || '후보 수집 실패');
        
        const cutoffStr = new Date(data.cutoff).toLocaleString();
        const skipped = [
            `점수 미달 ${data.skipped_low_score || 0}건`,
            `이미 학습 ${data.skipped_finalized || 0}건`,
            `기존 후보 ${data.skipped_duplicate || 0}건`
        ].join(', ');
        status.textContent = `${data.keywords.length}개 검색어에서 ${data.checked || 0}건을 검토했고, 새 후보 ${data.created || 0}건을 수집했습니다. (${skipped}, 기준: ${cutoffStr} 이후)`;
        
        showToast(`클리핑 후보 ${data.created}건 수집 완료`);
        await refreshCandidates();
    } catch (e) {
        console.error('Candidate collection failed:', e);
        const message = e.message || '후보 수집에 실패했습니다.';
        if (status) status.textContent = message;
        showToast(message);
    } finally {
        if (btn) btn.disabled = false;
    }
}

async function clearPendingCandidates() {
    const status = document.getElementById('candidateStatus');
    const btn = document.getElementById('clearPendingCandidatesBtn');

    if (candidateCurrentStatus !== 'pending' || !candidateCache.length) {
        showToast('비울 대기 후보가 없습니다.');
        return;
    }

    if (!confirm('현재 대기 중인 후보를 모두 삭제할까요? 제외한 후보 이력은 유지됩니다.')) {
        return;
    }

    if (btn) btn.disabled = true;
    if (status) status.textContent = '대기 후보를 비우는 중입니다...';

    try {
        const resp = await fetch('/api/clipping-candidates/clear-pending', { method: 'POST' });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || '대기 후보 삭제 실패');

        showToast(`대기 후보 ${data.deleted || 0}건을 삭제했습니다.`);
        await refreshCandidates();
    } catch (e) {
        console.error('Candidate clear failed:', e);
        const message = e.message || '대기 후보 삭제에 실패했습니다.';
        if (status) status.textContent = message;
        showToast(message);
    } finally {
        if (btn) btn.disabled = false;
    }
}

async function refreshCandidates() {
    const list = document.getElementById('candidateList');
    const status = document.getElementById('candidateStatus');
    const cutoffLabel = document.getElementById('currentCutoffLabel');
    const clearPendingBtn = document.getElementById('clearPendingCandidatesBtn');
    if (!list) return;

    try {
        const params = new URLSearchParams({ status: candidateCurrentStatus });
        const resp = await fetch(`/api/clipping-candidates?${params.toString()}`);
        if (resp.status === 401) {
            if (status) status.innerHTML = '인증이 만료되었습니다. <a href="/login">다시 로그인</a> 해주세요.';
            return;
        }
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || '후보 조회 실패');

        candidateCategories = data.categories || candidateCategories;
        candidateCache = data.items || [];
        candidateKeywords = data.keywords || [];

        renderCandidateKeywords(candidateKeywords);
        renderCandidateStatusTabs(data.status_counts || {});
        renderCandidates(candidateCache);
        if (clearPendingBtn) clearPendingBtn.disabled = candidateCurrentStatus !== 'pending' || candidateCache.length === 0;

        if (status) {
            const label = candidateStatusLabels[candidateCurrentStatus] || '후보';
            const cleanupText = data.cleanup_deleted
                ? ` 오래된 미검토 후보 ${data.cleanup_deleted}건은 자동 정리되었습니다.`
                : '';
            status.textContent = `${candidateKeywords.length}개 검색어, ${label} ${candidateCache.length}건을 표시 중입니다.${cleanupText}`;
        }

        if (cutoffLabel) {
            if (data.default_cutoff) {
                const date = new Date(data.default_cutoff);
                const timeStr = isNaN(date.getTime()) ? '형식 오류' : date.toLocaleString();
                cutoffLabel.textContent = ` 기준: ${timeStr}`;
            } else {
                cutoffLabel.textContent = ' 시점 데이터 없음';
            }
        }
    } catch (e) {
        console.error('Candidate refresh failed:', e);
        if (list) {
            list.innerHTML = `
                <div class="empty-state">
                    <p>후보 데이터를 불러오지 못했습니다. (네트워크 오류)</p>
                    <button class="btn-small" onclick="refreshCandidates()">다시 시도</button>
                </div>`;
        }
        if (cutoffLabel) cutoffLabel.textContent = ' 로드 실패';
    }
}
window.refreshCandidates = refreshCandidates;

function renderCandidateStatusTabs(counts) {
    document.querySelectorAll('[data-candidate-status]').forEach((tab) => {
        const status = tab.dataset.candidateStatus;
        tab.classList.toggle('active', status === candidateCurrentStatus);
    });

    document.querySelectorAll('[data-candidate-status-count]').forEach((badge) => {
        const status = badge.dataset.candidateStatusCount;
        badge.textContent = counts[status] || 0;
    });
}

function renderCandidateKeywords(keywords) {
    const list = document.getElementById('candidateKeywordList');
    if (!list) return;

    if (!keywords.length) {
        list.innerHTML = '<div class="candidate-keyword-empty">후보 수집 검색어가 없습니다.</div>';
        return;
    }

    list.innerHTML = keywords.map((keyword) => `
        <span class="candidate-keyword-chip">
            <span>${escapeHtml(keyword)}</span>
            <button type="button" data-candidate-keyword-remove data-keyword="${escapeAttr(keyword)}" aria-label="후보 수집 검색어 제거">×</button>
        </span>
    `).join('');
}

async function saveCandidateKeyword(keyword) {
    const resp = await fetch('/api/candidate-keywords', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ keyword })
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || '검색어 추가 실패');
    return data;
}

async function addCandidateKeyword(keyword) {
    const cleaned = String(keyword || '').trim();
    const input = document.getElementById('candidateKeywordInput');
    if (!cleaned) {
        showToast('추가할 검색어를 입력하세요.');
        return;
    }

    try {
        const data = await saveCandidateKeyword(cleaned);
        candidateKeywords = data.items || [];
        renderCandidateKeywords(candidateKeywords);
        if (input) input.value = '';
        
        const msg = data.created ? '후보 수집 검색어를 추가했습니다.' : '이미 등록된 후보 수집 검색어입니다.';
        showToast(msg);
        
        // If the user added from a search tab, they might want to know they need to run collection
        const status = document.getElementById('candidateStatus');
        if (status) {
             status.textContent = '후보 수집 검색어가 추가되었습니다. [후보 수집 시작] 버튼을 눌러 새 기사를 확인하세요.';
        }
    } catch (e) {
        console.error('Candidate keyword add failed:', e);
        showToast('후보 수집 검색어 추가에 실패했습니다.');
    }
}

function getOpenSearchTabKeywords() {
    const seen = new Set();
    return Array.from(document.querySelectorAll('.tab-pane[data-keyword]'))
        .map((panel) => String(panel.dataset.keyword || '').trim())
        .filter((keyword) => {
            if (!keyword || seen.has(keyword)) return false;
            seen.add(keyword);
            return true;
        });
}

async function addOpenSearchTabKeywords() {
    const btn = document.getElementById('addOpenSearchTabsBtn');
    const status = document.getElementById('candidateStatus');
    const openKeywords = getOpenSearchTabKeywords();

    if (!openKeywords.length) {
        showToast('현재 열린 검색결과 탭이 없습니다.');
        if (status) status.textContent = '먼저 검색어를 검색해 검색결과 탭을 열어주세요.';
        return;
    }

    const existing = new Set(candidateKeywords);
    const pendingKeywords = openKeywords.filter((keyword) => !existing.has(keyword));

    if (!pendingKeywords.length) {
        showToast('열린 검색결과 탭 키워드가 이미 모두 등록되어 있습니다.');
        if (status) status.textContent = '열린 검색결과 탭 키워드가 이미 후보 수집 검색어에 등록되어 있습니다.';
        return;
    }

    if (btn) btn.disabled = true;
    if (status) status.textContent = `${pendingKeywords.length}개 검색어를 후보 수집 목록에 추가하는 중입니다...`;

    try {
        let latestData = null;
        for (const keyword of pendingKeywords) {
            latestData = await saveCandidateKeyword(keyword);
        }

        if (latestData) {
            candidateKeywords = latestData.items || [];
            renderCandidateKeywords(candidateKeywords);
        }

        showToast(`열린 검색결과 탭 키워드 ${pendingKeywords.length}개를 추가했습니다.`);
        if (status) {
            status.textContent = '후보 수집 검색어가 추가되었습니다. 후보 수집 버튼을 눌러 새 기사를 확인하세요.';
        }
    } catch (e) {
        console.error('Open search tab keyword add failed:', e);
        showToast('열린 검색결과 탭 키워드 추가에 실패했습니다.');
        if (status) status.textContent = e.message || '열린 검색결과 탭 키워드 추가에 실패했습니다.';
    } finally {
        if (btn) btn.disabled = false;
    }
}

window.addCandidateKeywordFromSearch = async function(keyword) {
    await addCandidateKeyword(keyword);
};

async function removeCandidateKeyword(keyword) {
    try {
        const resp = await fetch('/api/candidate-keywords/remove', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ keyword })
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || '검색어 제거 실패');
        candidateKeywords = data.items || [];
        renderCandidateKeywords(candidateKeywords);
        showToast('후보 수집 검색어를 제거했습니다.');
    } catch (e) {
        console.error('Candidate keyword remove failed:', e);
        showToast('후보 수집 검색어 제거에 실패했습니다.');
    }
}

function isNegativeCandidateReason(reason) {
    const text = String(reason || '');
    return text.includes('제외한 기사') || /\s-\d+/.test(text);
}

function renderCandidateReason(reason) {
    const negative = isNegativeCandidateReason(reason);
    const badge = negative ? '<span class="candidate-reason-badge">감점</span>' : '';
    return `<li class="${negative ? 'negative-reason' : ''}">${badge}${escapeHtml(reason)}</li>`;
}

function renderCandidateActions(item) {
    if (item.status === 'pending') {
        return `
            <button type="button" class="btn-small btn-primary btn-clip-trigger" data-candidate-accept>클리핑</button>
            <button type="button" class="btn-small" data-candidate-reject>제외하고 학습에 반영</button>
            <button type="button" class="btn-small" data-candidate-open>원문 보기</button>
        `;
    }

    if (item.status === 'rejected') {
        return `
            <button type="button" class="btn-small btn-primary" data-candidate-restore>대기로 복원</button>
            <button type="button" class="btn-small btn-danger-light" data-candidate-delete>영구 삭제</button>
            <button type="button" class="btn-small" data-candidate-open>원문 보기</button>
        `;
    }

    return `
        <button type="button" class="btn-small btn-danger-light" data-candidate-delete>이력 삭제</button>
        <button type="button" class="btn-small" data-candidate-open>원문 보기</button>
    `;
}

function renderCandidates(items) {
    const list = document.getElementById('candidateList');
    if (!list) return;

    if (!items.length) {
        const label = candidateStatusLabels[candidateCurrentStatus] || '후보';
        list.innerHTML = `<div class="empty-state"><p>표시할 ${label}가 없습니다.</p></div>`;
        return;
    }

    list.innerHTML = items.map((item) => {
        const categoryOptions = item.status === 'pending' ? candidateCategories.map((category) => {
            const selected = category === item.suggested_category ? 'selected' : '';
            return `<option value="${escapeAttr(category)}" ${selected}>${escapeHtml(category)}</option>`;
        }).join('') : '';
        const similarBadge = item.similar_count > 0
            ? `<span class="candidate-badge">유사 ${item.similar_count}건</span>`
            : '';
        const negativeApplied = Array.isArray(item.score_reasons) && item.score_reasons.some(isNegativeCandidateReason)
            ? '<span class="candidate-badge candidate-negative-badge">제외 이력 감점</span>'
            : '';
        const reasons = Array.isArray(item.score_reasons) && item.score_reasons.length
            ? `<ul class="candidate-reasons">${item.score_reasons.map(renderCandidateReason).join('')}</ul>`
            : '<ul class="candidate-reasons"><li>점수 산정 사유 없음</li></ul>';
        const categoryControl = item.status === 'pending'
            ? `<select class="candidate-category-select" aria-label="후보 카테고리">${categoryOptions}</select>`
            : `<span class="candidate-category-static">${escapeHtml(item.suggested_category || '카테고리 없음')}</span>`;

        return `
            <div class="candidate-card" data-candidate-id="${item.id}">
                <div class="candidate-card-top">
                    <div class="candidate-meta">
                        <span>${escapeHtml(item.source || item.domain || '출처 미상')}</span>
                        <span>${escapeHtml(item.pub_date || '')}</span>
                        <span class="candidate-score">${item.score}점</span>
                        ${similarBadge}
                        ${negativeApplied}
                    </div>
                    ${categoryControl}
                </div>
                <h3>${escapeHtml(item.title)}</h3>
                <p>${escapeHtml(item.description || '')}</p>
                <div class="candidate-keyword">검색어: ${escapeHtml(item.keyword)}</div>
                ${reasons}
                <div class="news-actions">
                    ${renderCandidateActions(item)}
                </div>
            </div>
        `;
    }).join('');
}

let dashboardData = null;
const dashboardExcludedGroups = new Set();
const dashboardCategoryOverrides = new Map();

function setupDashboardActions() {
    const runBtn = document.getElementById('runDashboardBtn');
    const saveBtn = document.getElementById('saveDashboardFinalBtn');
    const refreshBtn = document.getElementById('refreshDashboardFinalBtn');
    const dashboardRoot = document.querySelector('.dashboard-workspace');
    const finalContent = document.getElementById('dashboardFinalContent');

    if (runBtn && !runBtn.dataset.bound) {
        runBtn.dataset.bound = 'true';
        runBtn.addEventListener('click', runDashboard);
    }

    if (saveBtn && !saveBtn.dataset.bound) {
        saveBtn.dataset.bound = 'true';
        saveBtn.addEventListener('click', saveDashboardFinal);
    }

    if (refreshBtn && !refreshBtn.dataset.bound) {
        refreshBtn.dataset.bound = 'true';
        refreshBtn.addEventListener('click', () => updateDashboardFinalContent(true));
    }

    if (dashboardRoot && !dashboardRoot.dataset.bound) {
        dashboardRoot.dataset.bound = 'true';
        dashboardRoot.addEventListener('click', (event) => {
            const excludeBtn = event.target.closest('[data-dashboard-exclude]');
            const openBtn = event.target.closest('[data-dashboard-open]');
            const restoreBtn = event.target.closest('[data-dashboard-restore]');
            const group = event.target.closest('[data-dashboard-group-id]');
            if (!group) return;

            const groupId = group.dataset.dashboardGroupId;
            const item = findDashboardItem(groupId);
            if (!item) return;

            if (openBtn) {
                const article = item.article || {};
                window.open(article.original_link || article.link, '_blank', 'noopener,noreferrer');
                return;
            }

            if (excludeBtn) {
                dashboardExcludedGroups.add(groupId);
                renderDashboard();
                updateDashboardFinalContent(true);
                showToast('대시보드 최종본에서 제외했습니다.');
                return;
            }

            if (restoreBtn) {
                dashboardExcludedGroups.delete(groupId);
                renderDashboard();
                updateDashboardFinalContent(true);
                showToast('제외한 기사를 다시 표시했습니다.');
            }
        });

        dashboardRoot.addEventListener('change', (event) => {
            const select = event.target.closest('[data-dashboard-category]');
            if (!select) return;
            const group = select.closest('[data-dashboard-group-id]');
            if (!group) return;
            dashboardCategoryOverrides.set(group.dataset.dashboardGroupId, select.value);
            renderDashboard();
            updateDashboardFinalContent(true);
        });
    }

    if (finalContent && !finalContent.dataset.bound) {
        finalContent.dataset.bound = 'true';
        finalContent.addEventListener('input', () => {
            finalContent.dataset.manualEdit = 'true';
        });
    }
}

async function runDashboard() {
    const btn = document.getElementById('runDashboardBtn');
    const status = document.getElementById('dashboardStatus');
    const saveBtn = document.getElementById('saveDashboardFinalBtn');

    if (btn) btn.disabled = true;
    if (saveBtn) saveBtn.disabled = true;
    if (status) status.textContent = '대시보드를 생성하는 중입니다...';

    try {
        const resp = await fetch('/api/dashboard/run', { method: 'POST', body: new FormData() });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || '대시보드 생성 실패');

        dashboardData = data.dashboard || null;
        dashboardExcludedGroups.clear();
        dashboardCategoryOverrides.clear();
        renderDashboard();
        updateDashboardFinalContent(true);

        if (saveBtn) saveBtn.disabled = !dashboardData || (dashboardData.issue_count || 0) === 0;
        if (status) {
            const dashboard = data.dashboard || {};
            const skipped = [
                `점수 미달 ${dashboard.skipped_low_score || 0}건`,
                `이미 학습 ${dashboard.skipped_finalized || 0}건`,
                `기존 후보 ${dashboard.skipped_duplicate || 0}건`
            ].join(', ');
            status.textContent = `${dashboard.checked || 0}건을 검토해 ${dashboard.issue_count || 0}개 이슈를 표시했습니다. (${skipped})`;
        }
        showToast('대시보드를 생성했습니다.');
    } catch (error) {
        console.error('Dashboard run failed:', error);
        if (status) status.textContent = error.message || '대시보드 생성에 실패했습니다.';
        showToast(error.message || '대시보드 생성에 실패했습니다.');
    } finally {
        if (btn) btn.disabled = false;
    }
}

function findDashboardItem(groupId) {
    if (!dashboardData || !Array.isArray(dashboardData.sections)) return null;
    for (const section of dashboardData.sections) {
        const found = (section.items || []).find(item => item.group_id === groupId);
        if (found) return found;
    }
    return null;
}

function getDashboardCategory(item) {
    return dashboardCategoryOverrides.get(item.group_id) || item.category || item.article?.suggested_category || '기타';
}

function getDashboardVisibleItems() {
    if (!dashboardData || !Array.isArray(dashboardData.sections)) return [];
    const items = [];
    dashboardData.sections.forEach(section => {
        (section.items || []).forEach(item => {
            if (!dashboardExcludedGroups.has(item.group_id)) {
                items.push(item);
            }
        });
    });
    return items;
}

function getDashboardExcludedItems() {
    return Array.from(dashboardExcludedGroups)
        .map(groupId => findDashboardItem(groupId))
        .filter(Boolean);
}

function formatDashboardDate(value) {
    if (!value) return '';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleString('ko-KR', { timeZone: 'Asia/Seoul' });
}

function formatDashboardEntryDate(value) {
    if (!value) return '';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '';
    const parts = new Intl.DateTimeFormat('en-US', {
        timeZone: 'Asia/Seoul',
        month: '2-digit',
        day: '2-digit'
    }).formatToParts(date);
    const month = parts.find(part => part.type === 'month')?.value || '';
    const day = parts.find(part => part.type === 'day')?.value || '';
    return ` (${month}.${day}.)`;
}

function renderDashboard() {
    const board = document.getElementById('dashboardBoard');
    const finalPanel = document.getElementById('dashboardFinalPanel');
    const checkedCount = document.getElementById('dashboardCheckedCount');
    const issueCount = document.getElementById('dashboardIssueCount');
    const relatedCount = document.getElementById('dashboardRelatedCount');
    const createdCount = document.getElementById('dashboardCreatedCount');
    const windowLabel = document.getElementById('dashboardWindowLabel');
    if (!board) return;

    if (!dashboardData) {
        return;
    }

    const visibleItems = getDashboardVisibleItems();
    if (checkedCount) checkedCount.textContent = dashboardData.checked || 0;
    if (issueCount) issueCount.textContent = visibleItems.length;
    if (relatedCount) {
        relatedCount.textContent = visibleItems.reduce((sum, item) => sum + (item.related_count || 0), 0);
    }
    if (createdCount) createdCount.textContent = dashboardData.created || 0;
    if (windowLabel) {
        windowLabel.textContent = `${formatDashboardDate(dashboardData.window_start)} ~ ${formatDashboardDate(dashboardData.window_end)}`;
    }
    if (finalPanel) finalPanel.hidden = false;
    renderDashboardExcluded();

    const sections = candidateCategories.map(category => {
        const items = visibleItems
            .filter(item => getDashboardCategory(item) === category)
            .sort((left, right) => (right.article?.score || 0) - (left.article?.score || 0));
        return { category, items };
    });

    board.innerHTML = sections.map(section => renderDashboardSection(section)).join('');
}

function renderDashboardExcluded() {
    const panel = document.getElementById('dashboardExcludedPanel');
    const list = document.getElementById('dashboardExcludedList');
    const count = document.getElementById('dashboardExcludedCount');
    if (!panel || !list) return;

    const items = getDashboardExcludedItems();
    panel.hidden = items.length === 0;
    if (count) count.textContent = `${items.length}건`;
    list.innerHTML = items.map(item => {
        const article = item.article || {};
        return `
            <div class="dashboard-excluded-item" data-dashboard-group-id="${escapeAttr(item.group_id)}">
                <div>
                    <strong>${escapeHtml(article.title || '제목 없음')}</strong>
                    <span>${escapeHtml(article.source || '출처 미상')}</span>
                </div>
                <button class="btn-small" type="button" data-dashboard-restore>복원</button>
            </div>
        `;
    }).join('');
}

function renderDashboardSection(section) {
    const items = section.items || [];
    const body = items.length
        ? items.map(renderDashboardIssueCard).join('')
        : '<div class="dashboard-empty">표시할 기사가 없습니다.</div>';
    return `
        <section class="dashboard-section">
            <div class="dashboard-section-header">
                <h3>${escapeHtml(section.category)}</h3>
                <span>${items.length}건</span>
            </div>
            <div class="dashboard-issue-list">
                ${body}
            </div>
        </section>
    `;
}

function renderDashboardIssueCard(item) {
    const article = item.article || {};
    const reasons = Array.isArray(article.score_reasons) && article.score_reasons.length
        ? article.score_reasons.slice(0, 4).map(reason => `<li>${escapeHtml(reason)}</li>`).join('')
        : '<li>점수 산정 사유 없음</li>';
    const categoryOptions = candidateCategories.map(category => {
        const selected = category === getDashboardCategory(item) ? 'selected' : '';
        return `<option value="${escapeAttr(category)}" ${selected}>${escapeHtml(category)}</option>`;
    }).join('');
    const related = Array.isArray(item.related_articles) && item.related_articles.length
        ? `
            <details class="dashboard-related">
                <summary>관련기사 ${item.related_articles.length}건</summary>
                <ul>
                    ${item.related_articles.map(relatedItem => `
                        <li>
                            <a href="${escapeAttr(relatedItem.original_link || relatedItem.link)}" target="_blank" rel="noopener noreferrer">
                                ${escapeHtml(relatedItem.source || '출처 미상')} · ${escapeHtml(relatedItem.title || '제목 없음')}
                            </a>
                        </li>
                    `).join('')}
                </ul>
            </details>
        `
        : '<div class="dashboard-related-empty">관련기사 0건</div>';

    return `
        <article class="dashboard-issue-card" data-dashboard-group-id="${escapeAttr(item.group_id)}">
            <div class="dashboard-card-top">
                <div class="dashboard-card-meta">
                    <span>${escapeHtml(article.source || '출처 미상')}</span>
                    <span>${escapeHtml(formatDashboardDate(article.pub_date))}</span>
                    <span class="dashboard-score">${article.score || 0}점</span>
                </div>
                <select data-dashboard-category aria-label="대시보드 기사 분류">
                    ${categoryOptions}
                </select>
            </div>
            <h4>${escapeHtml(article.title || '제목 없음')}</h4>
            <p>${escapeHtml(article.description || '')}</p>
            <ul class="dashboard-reasons">${reasons}</ul>
            ${related}
            <div class="news-actions">
                <button class="btn-small" type="button" data-dashboard-open>원문 보기</button>
                <button class="btn-small btn-danger-light" type="button" data-dashboard-exclude>대시보드에서 제외</button>
            </div>
        </article>
    `;
}

function buildDashboardFinalContent() {
    const items = getDashboardVisibleItems();
    const lines = [];
    candidateCategories.forEach(category => {
        lines.push(`■ ${category}`);
        lines.push('');
        items
            .filter(item => getDashboardCategory(item) === category)
            .sort((left, right) => (right.article?.score || 0) - (left.article?.score || 0))
            .forEach(item => {
                const article = item.article || {};
                const source = article.source || '출처 미상';
                const title = article.title || '제목 없음';
                const link = article.original_link || article.link || '';
                lines.push(`▷ ${source} : ${title}${formatDashboardEntryDate(article.pub_date)}`);
                if (link) lines.push(`<${link}>`);
                lines.push('');
            });
        lines.push('');
    });
    return `${lines.join('\n').trim()}\n`;
}

function updateDashboardFinalContent(force = false) {
    const finalContent = document.getElementById('dashboardFinalContent');
    if (!finalContent || !dashboardData) return;
    if (!force && finalContent.dataset.manualEdit === 'true') return;
    finalContent.value = buildDashboardFinalContent();
    finalContent.dataset.manualEdit = 'false';
}

async function saveDashboardFinal() {
    const btn = document.getElementById('saveDashboardFinalBtn');
    const status = document.getElementById('dashboardStatus');
    const finalContent = document.getElementById('dashboardFinalContent');
    const content = finalContent ? finalContent.value : buildDashboardFinalContent();
    if (!content.trim()) {
        showToast('저장할 최종본 내용이 없습니다.');
        return;
    }

    if (btn) btn.disabled = true;
    if (status) status.textContent = '대시보드 최종본을 저장하고 백업에 반영하는 중입니다...';

    try {
        const resp = await fetch('/api/dashboard/finalize', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ content })
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || '최종본 저장 실패');

        if (data.duplicate) {
            showToast('이미 저장된 대시보드 최종본입니다.');
            if (status) status.textContent = '이미 학습된 최종본과 동일한 내용입니다.';
        } else {
            const backupText = data.auto_backup ? ' GitHub 백업 완료' : '';
            showToast(`대시보드 최종본 ${data.entry_count || 0}건 저장 완료.${backupText}`);
            if (status) status.textContent = `최종본 ${data.entry_count || 0}건을 학습 이력에 저장했습니다.${backupText}`;
            if (data.backup_warning) showToast(`자동 백업 실패: ${data.backup_warning}`);
        }

        if (typeof window.refreshLearningStatus === 'function') {
            await window.refreshLearningStatus();
        }
        if (typeof window.refreshFinalizationHistory === 'function') {
            await window.refreshFinalizationHistory();
        }
    } catch (error) {
        console.error('Dashboard final save failed:', error);
        if (status) status.textContent = error.message || '대시보드 최종본 저장에 실패했습니다.';
        showToast(error.message || '대시보드 최종본 저장에 실패했습니다.');
    } finally {
        if (btn) btn.disabled = !dashboardData || getDashboardVisibleItems().length === 0;
    }
}

async function acceptCandidate(item, category, btnEl) {
    try {
        const resp = await fetch(`/api/clipping-candidates/${item.id}/accept`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ category })
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || '후보 반영 실패');

        if (window.clipArticleFromData) {
            window.clipArticleFromData(
                data.item.title,
                data.item.link,
                '',
                data.item.source,
                data.item.pub_date,
                data.item.original_link,
                btnEl,
                category,
                { skipRecord: true }
            );
        }

        showToast('후보를 클리핑에 반영했습니다.');
        await refreshCandidates();
    } catch (e) {
        console.error('Candidate accept failed:', e);
        showToast('후보 반영에 실패했습니다.');
    }
}

async function rejectCandidate(candidateId) {
    try {
        const resp = await fetch(`/api/clipping-candidates/${candidateId}/reject`, { method: 'POST' });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || '후보 제외 실패');
        showToast('후보를 제외했습니다.');
        await refreshCandidates();
    } catch (e) {
        console.error('Candidate reject failed:', e);
        showToast('후보 제외에 실패했습니다.');
    }
}

async function restoreCandidate(candidateId) {
    try {
        const resp = await fetch(`/api/clipping-candidates/${candidateId}/restore`, { method: 'POST' });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || '후보 복원 실패');
        showToast('제외 이력을 대기 후보로 복원했습니다.');
        await refreshCandidates();
    } catch (e) {
        console.error('Candidate restore failed:', e);
        showToast('후보 복원에 실패했습니다.');
    }
}

async function deleteCandidate(candidateId) {
    const item = candidateCache.find((candidate) => candidate.id === candidateId);
    const isRejected = item && item.status === 'rejected';
    const message = isRejected
        ? '이 제외 이력을 영구 삭제할까요? 삭제하면 이후 후보 감점 근거에서도 사라집니다.'
        : '이 후보 이력을 삭제할까요?';

    if (!confirm(message)) return;

    try {
        const resp = await fetch(`/api/clipping-candidates/${candidateId}/delete`, { method: 'POST' });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || '후보 삭제 실패');
        showToast('후보 이력을 삭제했습니다.');
        await refreshCandidates();
    } catch (e) {
        console.error('Candidate delete failed:', e);
        showToast('후보 삭제에 실패했습니다.');
    }
}


// ==============================================================================
// 5. INFINITE SCROLL LOGIC
// ==============================================================================

function setupInfiniteScrollForPanel(panel) {
    const sentinel = panel.querySelector('.panel-sentinel');
    if (!sentinel) return;

    // Remove existing observer if any
    if (panelObservers.has(panel.id)) {
        try { panelObservers.get(panel.id).disconnect(); } catch (e) { }
        panelObservers.delete(panel.id);
    }

    let loading = false;
    const observer = new IntersectionObserver(async (entries) => {
        for (const entry of entries) {
            if (!entry.isIntersecting) continue;
            if (loading) return;

            loading = true;
            const keyword = panel.dataset.keyword;
            let start = parseInt(panel.dataset.start || '1', 10);

            const fd = new FormData();
            fd.append('keyword', keyword);
            fd.append('start', start);

            try {
                const resp = await fetch('/search-results', { method: 'POST', body: fd });
                if (!resp.ok) {
                    sentinel.innerHTML = '추가 로드 실패';
                    observer.disconnect();
                    loading = false;
                    return;
                }
                const html = await resp.text();
                if (!html || html.trim().length === 0) {
                    sentinel.innerHTML = '더 이상 결과가 없습니다';
                    observer.disconnect();
                    loading = false;
                    return;
                }

                // Insert new items before the sentinel
                sentinel.insertAdjacentHTML('beforebegin', extractSearchContent(html, true));
                panel.dataset.start = String(start + 20);
                applySearchLayout();
                loading = false;
            } catch (err) {
                sentinel.innerHTML = '네트워크 오류';
                observer.disconnect();
                loading = false;
            }
        }
    }, {
        root: null,
        rootMargin: '400px'
    });

    observer.observe(sentinel);
    panelObservers.set(panel.id, observer);
}


// ==============================================================================
// 6. SEARCH LOGIC
// ==============================================================================

async function handleSearch() {
    const input = document.getElementById('keyword');
    if (!input) return;

    let keyword = input.value.trim();
    
    // Aggregating advanced search fields
    const advInclude = document.getElementById('advInclude');
    const advExclude = document.getElementById('advExclude');
    
    if (advInclude && advInclude.value.trim()) {
        keyword += ` +"${advInclude.value.trim()}"`;
    }
    if (advExclude && advExclude.value.trim()) {
        const excludes = advExclude.value.trim().split(/\s+/);
        excludes.forEach(ex => {
            keyword += ` -${ex}`;
        });
    }

    if (!keyword.trim()) {
        showToast('검색어를 입력하세요.');
        return;
    }

    // Hide advanced search panel if it was open
    const advancedPanel = document.getElementById('advancedSearchPanel');
    if (advancedPanel) advancedPanel.classList.remove('show');

    // Save to recent keywords (only the base search term)
    saveRecentKeyword(input.value.trim() || keyword);
    const el = document.getElementById('recentKeywords');
    if (el) el.classList.remove('show');

    // Check if tab already exists
    const existingTab = Array.from(document.querySelectorAll('.tab-pane')).find(p => p.dataset.keyword === keyword);
    if (existingTab) {
        switchTab(existingTab.id);
        showToast(`'${keyword}' 탭으로 이동했습니다.`);
        input.value = '';
        return;
    }

    // Create new tab
    const newTabId = createSearchTab(keyword, null);
    input.value = '';

    const fd = new FormData();
    fd.append('keyword', keyword);
    fd.append('start', 1);

    try {
        const resp = await fetch('/search-results', { method: 'POST', body: fd });
        if (resp.ok) {
            const html = await resp.text();
            const panel = document.getElementById(newTabId);
            if (panel) {
                const contentArea = panel.querySelector('.search-panel-content');
                if (contentArea) {
                    contentArea.innerHTML = extractSearchContent(html);
                    
                    syncSearchPanelControls(panel);
                    resetPanelSentinel(panel);
                }
                panel.dataset.start = '21';
                setupInfiniteScrollForPanel(panel);
                applySearchLayout();
            }
        } else {
            showToast('검색 실패: ' + resp.status);
            removeSearchTab(newTabId);
        }
    } catch (e) {
        showToast('검색 요청 오류');
        removeSearchTab(newTabId);
    }
}
window.handleSearch = handleSearch;


// Clipping Logic moved to clipping_service.js


// ==============================================================================
// 8. INITIALIZATION
// ==============================================================================

document.addEventListener('DOMContentLoaded', () => {
    // 1. Search Bar Event Listeners
    const searchBtn = document.getElementById('searchBtn');
    const input = document.getElementById('keyword');
    const recentKeywords = document.getElementById('recentKeywords');

    if (searchBtn) searchBtn.addEventListener('click', handleSearch);

    document.addEventListener('click', (event) => {
        const refreshBtn = event.target.closest('[data-search-refresh]');
        if (!refreshBtn) return;

        const panel = refreshBtn.closest('.tab-pane');
        if (!panel) return;
        refreshSearchTab(panel.id);
    });

    document.addEventListener('change', (event) => {
        const checkbox = event.target.closest('.watch-checkbox');
        if (!checkbox) return;
        window.toggleKeywordWatch(checkbox);
    });

    if (input) {
        input.addEventListener('keypress', (e) => { if (e.key === 'Enter') handleSearch(); });

        input.addEventListener('focus', () => {
            renderRecentKeywords();
            if (getRecentKeywords().length > 0) recentKeywords.classList.add('show');
        });

        input.addEventListener('blur', () => {
            // Delay hiding to allow click events on items
            setTimeout(() => { recentKeywords.classList.remove('show'); }, 200);
        });
    }

    // 1-1. Advanced Search Toggle
    const advancedToggleBtn = document.getElementById('advancedSearchToggleBtn');
    const advancedPanel = document.getElementById('advancedSearchPanel');

    if (advancedToggleBtn && advancedPanel) {
        advancedToggleBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            advancedPanel.classList.toggle('show');
            if (recentKeywords) recentKeywords.classList.remove('show');
        });
        
        // Prevent clicks inside panel from closing the panel accidentally or bubbling up
        advancedPanel.addEventListener('click', (e) => {
            e.stopPropagation();
        });
        
        // Listeners for advanced inputs enter key
        const advInclude = document.getElementById('advInclude');
        const advExclude = document.getElementById('advExclude');
        if (advInclude) advInclude.addEventListener('keypress', (e) => { if (e.key === 'Enter') handleSearch(); });
        if (advExclude) advExclude.addEventListener('keypress', (e) => { if (e.key === 'Enter') handleSearch(); });
    }

    // Close dropdowns when clicking outside
    document.addEventListener('click', (e) => {
        if (!e.target.closest('.search-box') && !e.target.closest('#advancedSearchPanel')) {
            if (advancedPanel) advancedPanel.classList.remove('show');
        }
    });

    // 2. Tab Navigation
    const tabsNav = document.querySelector('.tabs-nav');
    if (tabsNav) {
        tabsNav.addEventListener('click', (e) => {
            const btn = e.target.closest('button[data-tab]');
            if (!btn) return;

            const tabId = btn.dataset.tab;
            if (tabId === 'candidates') loadCandidatesTab();
            if (tabId === 'clippings') loadClippingsTab();
            switchTab(tabId);
        });
    }
    setupDashboardActions();

    // 4. Load Default Search Tabs
    async function loadDefaultSearch() {
        const keywords = Array.isArray(window.defaultSearchKeywords) ? window.defaultSearchKeywords : [];
        for (const kw of keywords) {
            const fd = new FormData();
            fd.append('keyword', kw);
            fd.append('start', 1);
            try {
                const resp = await fetch('/search-results', { method: 'POST', body: fd });
                if (resp.ok) {
                    const html = await resp.text();
                    createSearchTab(kw, html, 21, false);
                }
            } catch (e) {
                console.error('기본 검색 오류:', e);
            }
        }
    }


    // 5. Global Keyboard Shortcuts
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            if (document.activeElement === input) {
                input.blur();
            }
        }
    });

    // 5-1. Scroll Controls Logic
    const scrollControls = document.getElementById('scrollControls');
    const scrollTopBtn = document.getElementById('scrollTopBtn');
    const scrollBottomBtn = document.getElementById('scrollBottomBtn');

    if (scrollControls) {
        window.addEventListener('scroll', () => {
            if (window.scrollY > 300) {
                scrollControls.classList.add('show');
            } else {
                scrollControls.classList.remove('show');
            }
        });
    }

    if (scrollTopBtn) {
        scrollTopBtn.addEventListener('click', () => {
            window.scrollTo({ top: 0, behavior: 'smooth' });
        });
    }

    if (scrollBottomBtn) {
        scrollBottomBtn.addEventListener('click', () => {
            window.scrollTo({ top: document.documentElement.scrollHeight, behavior: 'smooth' });
        });
    }

    function getThemeIcon(isDark) {
        const path = isDark
            ? 'M12 3v2.5M12 18.5V21M4.9 4.9l1.8 1.8M17.3 17.3l1.8 1.8M3 12h2.5M18.5 12H21M4.9 19.1l1.8-1.8M17.3 6.7l1.8-1.8M16.5 12a4.5 4.5 0 1 1-9 0 4.5 4.5 0 0 1 9 0Z'
            : 'M21 12.8A8.5 8.5 0 1 1 11.2 3a6.8 6.8 0 0 0 9.8 9.8Z';
        return `
            <span class="button-icon" aria-hidden="true">
                <svg viewBox="0 0 24 24" focusable="false">
                    <path d="${path}"></path>
                </svg>
            </span>
        `;
    }

    function updateThemeButton(isDark) {
        const btn = document.querySelector('.theme-btn');
        if (!btn) return;

        btn.innerHTML = getThemeIcon(isDark);
        const label = isDark ? '라이트 모드로 전환' : '다크 모드로 전환';
        btn.setAttribute('aria-label', label);
        btn.setAttribute('title', label);
    }

    // 6. Theme Toggle (Dark Mode)
    window.toggleTheme = function () {
        document.body.classList.toggle('dark-mode');
        const isDark = document.body.classList.contains('dark-mode');
        localStorage.setItem('theme', isDark ? 'dark' : 'light');

        updateThemeButton(isDark);

        // Toggle Toast UI Editor theme class if it exists
        if (window.clippingEditor) {
            const editorUI = document.querySelector('.toastui-editor-defaultUI');
            if (editorUI) {
                if (isDark) {
                    editorUI.classList.add('toastui-editor-dark');
                } else {
                    editorUI.classList.remove('toastui-editor-dark');
                }
            }
        }
    };

    // Load saved theme
    const savedTheme = localStorage.getItem('theme');
    if (savedTheme === 'dark') {
        document.body.classList.add('dark-mode');
    }
    updateThemeButton(document.body.classList.contains('dark-mode'));

    // 7. SSE Notifications & Desktop Alerts
    function showBrowserNotification(message) {
        if (!("Notification" in window)) return;
        
        if (Notification.permission === "granted") {
            const notification = new Notification("뉴스 클리핑 알림", {
                body: message,
                icon: '/static/img/logo.png' 
            });
            notification.onclick = function() {
                window.focus();
                this.close();
            };
        }
    }

    let sseWatchdog = null;
    const RECENT_NOTIF_CACHE = new Set(); // To prevent duplicate toasts during catch-up

    function initSSE() {
        if (window.eventSource) {
            window.eventSource.close();
        }

        const url = `/api/stream/notifications?client_id=${encodeURIComponent(window.sseClientId)}`;
        const eventSource = new EventSource(url);
        window.eventSource = eventSource;
        
        const resetWatchdog = () => {
            if (sseWatchdog) clearTimeout(sseWatchdog);
            sseWatchdog = setTimeout(() => {
                console.warn('SSE Watchdog: No activity for 45s, reconnecting...');
                initSSE();
            }, 45000);
        };

        eventSource.onopen = () => {
            console.log('SSE connection opened');
            resetWatchdog();
        };

        eventSource.onmessage = function (event) {
            resetWatchdog();
            if (event.data) {
                // Heartbeat check (skip ": ping")
                if (event.data === 'ping') return;

                // Client ID Confirmation
                if (event.data.startsWith('connected:')) {
                    const cid = event.data.split(':')[1];
                    console.log('SSE Connected as:', cid);
                    
                    // 🔄 Absolute Sync: Send the ENTIRE current watch list to the server
                    // This ensures any ghost keywords are removed on the server side
                    if (window.keywordWatchSet) {
                        syncAlertsWithServer();
                        renderActiveAlerts();
                    }
                    return;
                }

                // 3. Auto-Refresh Logic
                const match = event.data.match(/\[(.*?)\]/);
                if (match && match[1]) {
                    const notifyKeyword = match[1];
                    
                    // Only show notifications and refresh if the user HAS enabled alerts for this keyword
                    if (window.keywordWatchSet && window.keywordWatchSet.has(notifyKeyword)) {
                        
                        // Prevent duplicate toasts (especially during catch-up)
                        const notifKey = `${notifyKeyword}:${event.data}`;
                        if (RECENT_NOTIF_CACHE.has(notifKey)) return;
                        
                        RECENT_NOTIF_CACHE.add(notifKey);
                        setTimeout(() => RECENT_NOTIF_CACHE.delete(notifKey), 10000); // 10s expiry

                        // 1. UI Toast
                        showToast('🔔 ' + event.data);
                        
                        // 2. Browser Desktop Notification
                        showBrowserNotification(event.data);

                        // 3. Auto-Refresh matching tabs
                        document.querySelectorAll('.tab-pane').forEach(panel => {
                            if (panel.dataset.keyword === notifyKeyword) {
                                console.log(`Auto-refreshing tab ${panel.id} for keyword: ${notifyKeyword}`);
                                refreshSearchTab(panel.id);
                            }
                        });
                    }
                }
            }
        };

        eventSource.onerror = (e) => {
            console.warn('SSE connection error, will retry...', e);
            if (sseWatchdog) clearTimeout(sseWatchdog);
            eventSource.close();
            setTimeout(initSSE, 5000); 
        };
    }

    try {
        initSSE();

        // Request Permission on first user interaction
        const requestPermissionOnce = () => {
            if ("Notification" in window && Notification.permission === "default") {
                Notification.requestPermission();
            }
            document.removeEventListener('click', requestPermissionOnce);
        };
        document.addEventListener('click', requestPermissionOnce);

    } catch (e) {
        console.error('SSE initialization error:', e);
    }

    const clearAllAlertsBtn = document.getElementById('clearAllAlertsBtn');
    if (clearAllAlertsBtn) {
        clearAllAlertsBtn.addEventListener('click', clearAllAlerts);
    }

    // Load default search tabs on startup
    applySearchLayout();
    loadDefaultSearch();
});
