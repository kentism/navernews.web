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
    return (s || '').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

/**
 * Displays a temporary toast message.
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
    setTimeout(() => toast.remove(), 3000);
}
// Expose to window for inline calls if necessary
window.showToast = showToast;

window.toggleKeywordWatch = async function(el) {
    const keyword = el.dataset.keyword;
    const isChecked = el.checked;
    const clientId = window.sseClientId;

    const url = isChecked ? '/api/watch' : '/api/unwatch';
    const formData = new FormData();
    formData.append('keyword', keyword);
    formData.append('client_id', clientId);

    try {
        const resp = await fetch(url, { method: 'POST', body: formData });
        if (resp.ok) {
            if (isChecked) {
                window.keywordWatchSet.add(keyword);
                showToast(`🔔 [${keyword}] 실시간 알림을 시작합니다.`);
            } else {
                window.keywordWatchSet.delete(keyword);
                showToast(`🔕 [${keyword}] 실시간 알림을 중단합니다.`);
            }
            localStorage.setItem('watchedKeywords', JSON.stringify(Array.from(window.keywordWatchSet)));
            
            // 🔄 Update manager UI if it exists
            renderActiveAlerts();
        } else {
            console.error('Failed to update watch status:', resp.status);
            showToast('알림 설정 실패');
            el.checked = !isChecked;
        }
    } catch (e) {
        console.error('Watch toggle error:', e);
        showToast('알림 서버 통신 오류');
        el.checked = !isChecked;
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

    window.keywordWatchSet.delete(keyword);
    localStorage.setItem('watchedKeywords', JSON.stringify(Array.from(window.keywordWatchSet)));

    // Sync with server (Absolute Sync)
    syncAlertsWithServer();

    // Update UI
    renderActiveAlerts();
    
    // Sync any visible checkboxes in search tabs
    document.querySelectorAll(`.watch-checkbox[data-keyword="${keyword}"]`).forEach(cb => {
        cb.checked = false;
    });

    showToast(`🔕 [${keyword}] 알림이 중단되었습니다.`);
};

/**
 * Clears all active alerts.
 */
async function clearAllAlerts() {
    if (window.keywordWatchSet.size === 0) return;
    if (!confirm('정말로 모든 실시간 알림을 초기화하시겠습니까?')) return;

    window.keywordWatchSet.clear();
    localStorage.setItem('watchedKeywords', JSON.stringify([]));

    // Sync with server (Absolute Sync)
    syncAlertsWithServer();

    // Update UI
    renderActiveAlerts();

    // Sync all visible checkboxes
    document.querySelectorAll('.watch-checkbox').forEach(cb => {
        cb.checked = false;
    });

    showToast('🗑️ 모든 실시간 알림이 초기화되었습니다.');
}
window.clearAllAlerts = clearAllAlerts;

/**
 * Authoritative sync with server
 */
function syncAlertsWithServer() {
    const keywords = Array.from(window.keywordWatchSet || []);
    fetch('/api/sync-watch', { 
        method: 'POST', 
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            client_id: window.sseClientId,
            keywords: keywords
        })
    }).catch(e => console.error('Sync error:', e));
}



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

    if (contentArea) {
        contentArea.innerHTML = getSkeletonHTML();
        showToast(`'${keyword}' 검색 결과를 새로고침하는 중...`);
    }

    const fd = new FormData();
    fd.append('keyword', keyword);
    fd.append('start', 1);
    fd.append('refresh', 'true');

    try {
        const resp = await fetch('/search-results', { method: 'POST', body: fd });
        if (!resp.ok) {
            showToast('새로고침 실패: 서버 오류');
            if (contentArea) contentArea.innerHTML = '<div class="empty-state"><p>새로고침에 실패했습니다.</p></div>';
            return;
        }
        const html = await resp.text();

        if (contentArea) {
            contentArea.innerHTML = extractSearchContent(html);
            const sentinel = document.createElement('div');
            sentinel.className = 'panel-sentinel';
            sentinel.innerHTML = getSentinelHTML();
            contentArea.appendChild(sentinel);
        }
        panel.dataset.start = '21';
        setupInfiniteScrollForPanel(panel);
        applySearchLayout();
        showToast(`✅ '${keyword}' 검색 결과를 새로고침 완료했습니다.`);
    } catch (e) {
        console.error('새로고침 오류:', e);
        showToast('❌ 새로고침 중 네트워크 오류가 발생했습니다.');
        if (contentArea) contentArea.innerHTML = '<div class="empty-state"><p>네트워크 오류로 새로고침에 실패했습니다.</p></div>';
    }
}

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

async function loadAlertsTab() {
    const alertsPane = document.getElementById('alerts');
    if (!alertsPane) return;

    let innerContainer = alertsPane.querySelector('.tab-content-inner');
    if (!innerContainer) {
        innerContainer = document.createElement('div');
        innerContainer.className = 'tab-content-inner';
        alertsPane.appendChild(innerContainer);
    }

    const hasContent = innerContainer.querySelector('#alertManagerSection');
    if (hasContent) {
        renderActiveAlerts();
        return;
    }

    innerContainer.innerHTML = '<div class="loading-state">알림 센터를 로드하는 중...</div>';

    try {
        const resp = await fetch('/alerts-tab');
        const html = await resp.text();
        innerContainer.innerHTML = html;
        renderActiveAlerts();

        const clearAllAlertsBtn = document.getElementById('clearAllAlertsBtn');
        if (clearAllAlertsBtn) {
            clearAllAlertsBtn.addEventListener('click', clearAllAlerts);
        }
    } catch (e) {
        console.error('알림 센터 로드 실패:', e);
        innerContainer.innerHTML = '<div class="error-state">알림 센터를 불러오는데 실패했습니다.</div>';
    }
}
window.loadAlertsTab = loadAlertsTab;


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
                    
                    // Sync toggle state
                    const checkbox = panel.querySelector('.watch-checkbox');
                    if (checkbox && window.keywordWatchSet) {
                        checkbox.checked = window.keywordWatchSet.has(checkbox.dataset.keyword);
                    }

                    const sentinel = document.createElement('div');
                    sentinel.className = 'panel-sentinel';
                    sentinel.innerHTML = getSentinelHTML();
                    contentArea.appendChild(sentinel);
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
            if (tabId === 'alerts') loadAlertsTab();
            if (tabId === 'clippings') loadClippingsTab();
            switchTab(tabId);
        });
    }

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

    // 6. Theme Toggle (Dark Mode)
    window.toggleTheme = function () {
        document.body.classList.toggle('dark-mode');
        const isDark = document.body.classList.contains('dark-mode');
        localStorage.setItem('theme', isDark ? 'dark' : 'light');

        const btn = document.querySelector('.theme-btn');
        if (btn) btn.textContent = isDark ? '☀️' : '🌙';

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
        const btn = document.querySelector('.theme-btn');
        if (btn) btn.textContent = '☀️';
    }

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
