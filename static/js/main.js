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
const CLIPPING_TEXT_KEY = 'clippedTextContent';

// Default text for the clipping memo pad
const DEFAULT_CLIPPED_TEXT = '■ 위원회 관련\n\n■ 방송·통신 관련\n\n■ 유관기관 관련\n\n■ 기타 관련\n\n';

// Global state
let searchTabCounter = 0;
const panelObservers = new Map(); // Stores IntersectionObservers for infinite scroll


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
 * Creates a new search result tab.
 */
function createSearchTab(keyword, htmlContent, start = 1, activate = true) {
    const id = 'search-' + (++searchTabCounter) + '-' + Date.now().toString(36);

    // 1. Create Tab Button
    const btn = document.createElement('button');
    btn.className = 'tab-btn';
    btn.dataset.tab = id;
    // Truncate long keywords
    btn.textContent = keyword.length > 20 ? keyword.slice(0, 17) + '…' : keyword;

    const close = document.createElement('span');
    close.textContent = ' ×';
    close.style.marginLeft = '8px';
    close.onclick = (e) => {
        e.stopPropagation();
        removeSearchTab(id);
    };
    btn.appendChild(close);

    // Insert button before the refresh button
    const navContainer = document.querySelector('.tabs-nav');
    const refreshBtn = document.getElementById('globalRefreshBtn');
    if (navContainer && refreshBtn) {
        navContainer.insertBefore(btn, refreshBtn);
    } else if (navContainer) {
        navContainer.appendChild(btn);
    }

    // 2. Create Tab Panel
    const panel = document.createElement('div');
    panel.className = 'tab-pane';
    panel.id = id;
    panel.dataset.keyword = keyword;
    panel.dataset.start = String(start);

    panel.innerHTML = `<div class="search-panel-content">${htmlContent || getSkeletonHTML()}</div>`;

    // Add Sentinel for Infinite Scroll
    const sentinel = document.createElement('div');
    sentinel.className = 'panel-sentinel';
    sentinel.textContent = '로딩...';

    const innerDiv = panel.querySelector('.search-panel-content');
    if (innerDiv) innerDiv.appendChild(sentinel);

    document.querySelector('.tabs-content').appendChild(panel);

    // Activate and Setup
    if (activate) {
        switchTab(id);
    }
    setupInfiniteScrollForPanel(panel);
    return id;
}

function removeSearchTab(id) {
    const btn = document.querySelector(`.tabs-nav [data-tab="${id}"]`);
    const panel = document.getElementById(id);

    if (btn) btn.remove();
    if (panel) {
        // Clean up observer
        if (panelObservers.has(id)) {
            try { panelObservers.get(id).disconnect(); } catch (e) { }
            panelObservers.delete(id);
        }
        panel.remove();
    }

    // Switch to the last remaining tab
    const remainingTabs = document.querySelectorAll('.tabs-nav .tab-btn');
    const lastSearchTab = Array.from(remainingTabs).filter(t => t.id !== 'clippingsBtn').pop();

    if (lastSearchTab) {
        switchTab(lastSearchTab.dataset.tab);
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

    try {
        const resp = await fetch('/search-results', { method: 'POST', body: fd });
        if (!resp.ok) {
            showToast('새로고침 실패: 서버 오류');
            if (contentArea) contentArea.innerHTML = '<div class="empty-state"><p>새로고침에 실패했습니다.</p></div>';
            return;
        }
        const html = await resp.text();

        if (contentArea) {
            contentArea.innerHTML = html;
            const sentinel = document.createElement('div');
            sentinel.className = 'panel-sentinel';
            sentinel.textContent = '로딩...';
            contentArea.appendChild(sentinel);
        }
        panel.dataset.start = '21';
        setupInfiniteScrollForPanel(panel);
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
    if (panel) panel.classList.add('active');

    // Toggle Global Refresh Button visibility
    const refreshBtn = document.getElementById('globalRefreshBtn');
    if (refreshBtn) {
        // Only show refresh button for search tabs (not clippings)
        const isSearchTabActive = tabBtn && tabBtn.dataset.tab.startsWith('search-');
        refreshBtn.style.display = isSearchTabActive ? 'block' : 'none';
    }

    // Toggle Initial Message
    const hasSearchResults = !!document.querySelector('.tabs-nav button[data-tab^="search-"]');
    const initialMessage = document.getElementById('initialSearchMessage');
    if (initialMessage) {
        initialMessage.style.display = hasSearchResults ? 'none' : 'block';
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
                    sentinel.textContent = '추가 로드 실패';
                    observer.disconnect();
                    loading = false;
                    return;
                }
                const html = await resp.text();
                if (!html || html.trim().length === 0) {
                    sentinel.textContent = '더 이상 결과가 없습니다';
                    observer.disconnect();
                    loading = false;
                    return;
                }

                // Insert new items before the sentinel
                sentinel.insertAdjacentHTML('beforebegin', html);
                panel.dataset.start = String(start + 20);
                loading = false;
            } catch (err) {
                sentinel.textContent = '네트워크 오류';
                observer.disconnect();
                loading = false;
            }
        }
    }, {
        root: panel,
        rootMargin: '200px'
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

    const keyword = input.value.trim();
    if (!keyword) {
        showToast('검색어를 입력하세요.');
        return;
    }

    // Save to recent keywords
    saveRecentKeyword(keyword);
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
                    contentArea.innerHTML = html;
                    const sentinel = document.createElement('div');
                    sentinel.className = 'panel-sentinel';
                    sentinel.textContent = '로딩...';
                    contentArea.appendChild(sentinel);
                }
                panel.dataset.start = '21';
                setupInfiniteScrollForPanel(panel);
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


// ==============================================================================
// 7. CLIPPING LOGIC (TEXT AREA ONLY)
// ==============================================================================

/**
 * Loads the clippings tab content and initializes the text area.
 */
window.loadClippingsTab = async function () {
    const clippingsPane = document.getElementById('clippings');
    if (!clippingsPane) return;

    let innerContainer = clippingsPane.querySelector('.tab-content-inner');
    if (!innerContainer) {
        innerContainer = document.createElement('div');
        innerContainer.className = 'tab-content-inner';
        clippingsPane.appendChild(innerContainer);
    }

    // Check if content already loaded by looking for more than loading message
    const hasContent = innerContainer.querySelector('#clippingTextArea');
    if (hasContent) return;

    innerContainer.innerHTML = '클리핑을 로드하는 중...';

    try {
        const resp = await fetch('/clippings-tab');
        const html = await resp.text();

        innerContainer.innerHTML = html;

        // Initialize Text Area with saved content
        const textArea = document.getElementById('clippingTextArea');
        if (textArea) {
            const savedText = localStorage.getItem(CLIPPING_TEXT_KEY) || DEFAULT_CLIPPED_TEXT;
            textArea.value = savedText;

            // Add auto-save listener
            textArea.addEventListener('input', () => {
                localStorage.setItem(CLIPPING_TEXT_KEY, textArea.value);
            });
        }

        // Setup Copy Button
        const copyBtn = document.getElementById('copyTextBtn');
        if (copyBtn) {
            copyBtn.addEventListener('click', () => {
                if (!textArea || !textArea.value) return;

                // Modern Clipboard API (HTTPS/localhost only)
                if (navigator.clipboard && window.isSecureContext) {
                    navigator.clipboard.writeText(textArea.value)
                        .then(() => showToast('📋 클리핑 텍스트가 복사되었습니다.'))
                        .catch(err => {
                            console.error('복사 실패:', err);
                            showToast('복사에 실패했습니다.');
                        });
                } else {
                    // Fallback for HTTP or older browsers
                    try {
                        textArea.select();
                        textArea.setSelectionRange(0, 99999); // Mobile compatibility
                        document.execCommand('copy');
                        showToast('📋 클리핑 텍스트가 복사되었습니다.');
                    } catch (e) {
                        console.error('대체 복사 방식 실패:', e);
                        alert('복사에 실패했습니다. 브라우저 설정을 확인해주세요.');
                    }
                    // Deselect
                    window.getSelection()?.removeAllRanges();
                }
            });
        }

        // Setup Clear Button
        const clearBtn = document.getElementById('clearTextBtn');
        if (clearBtn) {
            clearBtn.addEventListener('click', () => {
                if (textArea) {
                    textArea.value = DEFAULT_CLIPPED_TEXT;
                    localStorage.setItem(CLIPPING_TEXT_KEY, DEFAULT_CLIPPED_TEXT);
                    showToast('✨ 텍스트를 초기화했습니다.');
                }
            });
        }

    } catch (e) {
        console.error('클리핑 탭 로드 실패:', e);
        innerContainer.innerHTML = '<div class="error-state">클리핑 탭을 불러오는데 실패했습니다.</div>';
    }
};

/**
 * Appends article info to the clipping text area.
 */
/**
 * Clips an article to the text area, categorized by section.
 */
function clipArticleFromData(title, link, content, source, pubDate, originalLink, btnEl, category) {
    const textArea = document.getElementById('clippingTextArea');
    let currentText = textArea ? textArea.value : (localStorage.getItem(CLIPPING_TEXT_KEY) || DEFAULT_CLIPPED_TEXT);

    // Format date: extract MM.DD. from pubDate
    let formattedDate = '';
    if (pubDate) {
        try {
            const dateObj = new Date(pubDate);
            const month = String(dateObj.getMonth() + 1).padStart(2, '0');
            const day = String(dateObj.getDate()).padStart(2, '0');
            formattedDate = `${month}.${day}.`;
        } catch (e) {
            formattedDate = '';
        }
    }

    // Format the new entry
    const newEntry = `▷ ${source} : ${title} (${formattedDate})\n${originalLink}\n`;

    // Categorized Insertion Logic
    if (category) {
        const header = `■ ${category}`;
        const lines = currentText.split('\n');
        let headerIndex = -1;

        // Find the category header
        for (let i = 0; i < lines.length; i++) {
            if (lines[i].includes(header)) {
                headerIndex = i;
                break;
            }
        }

        if (headerIndex !== -1) {
            // Find insertion point: after the header and any existing entries in this section
            let insertAt = headerIndex + 1;
            while (insertAt < lines.length && (lines[insertAt].trim() === '' || lines[insertAt].startsWith('▷') || lines[insertAt].startsWith('http'))) {
                // If we hit another header, stop
                if (lines[insertAt].startsWith('■')) break;
                insertAt++;
            }

            // Adjust: if the line before insertion is empty, but we have content later, or if it's the very next line
            lines.splice(insertAt, 0, newEntry);
            currentText = lines.join('\n');
        } else {
            // Header not found, fallback to append
            currentText += `\n${header}\n${newEntry}`;
        }
    } else {
        // Fallback for uncategorized
        currentText += `\n${newEntry}`;
    }

    // Save
    localStorage.setItem(CLIPPING_TEXT_KEY, currentText);

    // Update UI if visible
    if (textArea) {
        textArea.value = currentText;
        // Scroll to bottom is not always ideal for middle insertion, but helps visibility
        textArea.scrollTop = textArea.scrollHeight;
    }

    showToast(`✅ [${category}]에 추가되었습니다.`);

    // Visual feedback
    if (btnEl) {
        const originalText = btnEl.textContent;
        btnEl.textContent = '저장됨!';
        btnEl.disabled = true;
        setTimeout(() => {
            btnEl.textContent = originalText;
            btnEl.disabled = false;
        }, 2000);
    }
}
window.clipArticleFromData = clipArticleFromData;


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

    // 2. Tab Navigation
    const tabsNav = document.querySelector('.tabs-nav');
    if (tabsNav) {
        tabsNav.addEventListener('click', (e) => {
            const btn = e.target.closest('button[data-tab]');
            if (!btn) return;

            const tabId = btn.dataset.tab;
            if (tabId === 'clippings') loadClippingsTab();
            switchTab(tabId);
        });
    }

    // 3. Global Refresh Button
    const globalRefreshBtn = document.getElementById('globalRefreshBtn');
    if (globalRefreshBtn) {
        globalRefreshBtn.addEventListener('click', () => {
            const activeTab = document.querySelector('.tab-pane.active');
            if (activeTab && activeTab.id && activeTab.id.startsWith('search-')) {
                refreshSearchTab(activeTab.id);
            }
        });
    }

    // 4. Load Default Search Tabs
    async function loadDefaultSearch() {
        const keywords = ['방송미디어통신심의위원회', '방송미디어통신위원회', '과방위'];
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

    // 6. Theme Toggle (Dark Mode)
    window.toggleTheme = function () {
        document.body.classList.toggle('dark-mode');
        const isDark = document.body.classList.contains('dark-mode');
        localStorage.setItem('theme', isDark ? 'dark' : 'light');

        const btn = document.querySelector('.theme-btn');
        if (btn) btn.textContent = isDark ? '☀️' : '🌙';
    };

    // Load saved theme
    const savedTheme = localStorage.getItem('theme');
    if (savedTheme === 'dark') {
        document.body.classList.add('dark-mode');
        const btn = document.querySelector('.theme-btn');
        if (btn) btn.textContent = '☀️';
    }

    // Load default search tabs on startup
    loadDefaultSearch();
});