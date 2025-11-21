// 1. localStorage 키 설정
const CLIPS_STORAGE_KEY = 'navernews_clips';
const RECENT_KEYWORDS_KEY = 'navernews_recent_keywords';

// ⭐⭐ [수정] 4. 탭 및 검색 로직 변수 (전역으로 이동) ⭐⭐
let searchTabCounter = 0;
const panelObservers = new Map();
// clippedTextContent와 defaultClippedText를 전역에서 정의 및 localStorage 연동
const defaultClippedText = '■ 위원회 관련\n\n■ 방송·통신 관련\n\n■ 유관기관 관련\n\n■ 기타 관련\n\n';
let clippedTextContent = localStorage.getItem('clippedTextContent') || defaultClippedText;
// ⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐

// 2. 유틸리티 함수들 (HTML 이스케이프 등)
function escapeHtml(s) { return String(s || '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }
function escapeAttr(s) { return (s || '').replace(/"/g, '&quot;').replace(/'/g, '&#39;'); }

// 토스트 알림
function showToast(message) {
    const container = document.getElementById('toastContainer');
    if (!container) return;
    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => toast.classList.add('show'), 10);
    setTimeout(() => toast.remove(), 3000);
}
window.showToast = showToast;

// 3. 최근 검색어 관련 함수
function getRecentKeywords() {
    const data = localStorage.getItem(RECENT_KEYWORDS_KEY);
    return data ? JSON.parse(data) : [];
}

function saveRecentKeyword(keyword) {
    if (!keyword) return;
    let keywords = getRecentKeywords();
    keywords = keywords.filter(k => k !== keyword);
    keywords.unshift(keyword);
    if (keywords.length > 10) keywords.pop();
    localStorage.setItem(RECENT_KEYWORDS_KEY, JSON.stringify(keywords));
}

function deleteRecentKeyword(keyword, event) {
    if (event) event.stopPropagation();
    let keywords = getRecentKeywords();
    keywords = keywords.filter(k => k !== keyword);
    localStorage.setItem(RECENT_KEYWORDS_KEY, JSON.stringify(keywords));
    renderRecentKeywords();
    if (keywords.length === 0) {
        const el = document.getElementById('recentKeywords');
        if (el) el.classList.remove('show');
    }
}

function renderRecentKeywords() {
    const container = document.getElementById('recentKeywords');
    if (!container) return;
    const keywords = getRecentKeywords();
    if (keywords.length === 0) {
        container.innerHTML = '';
        container.classList.remove('show');
        return;
    }
    let html = '<div class="recent-keywords-header">최근 검색어</div>';
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

// 스켈레톤 HTML 반환
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

// 5. 탭 생성 및 관리 (이전과 동일)
function createSearchTab(keyword, htmlContent, start = 1) {
    // ... (createSearchTab 함수 본문 유지) ...
    const id = 'search-' + (++searchTabCounter) + '-' + Date.now().toString(36);

    // 탭 버튼 생성
    const btn = document.createElement('button');
    btn.className = 'tab-btn';
    btn.dataset.tab = id;
    btn.textContent = keyword.length > 20 ? keyword.slice(0, 17) + '…' : keyword;

    const close = document.createElement('span');
    close.textContent = ' ×';
    close.style.marginLeft = '8px';
    close.onclick = (e) => {
        e.stopPropagation();
        removeSearchTab(id);
    };
    btn.appendChild(close);

    // 탭 버튼 삽입 위치 조정
    const navContainer = document.querySelector('.tabs-nav');
    const refreshBtn = document.getElementById('globalRefreshBtn');
    if (navContainer && refreshBtn) {
        navContainer.insertBefore(btn, refreshBtn);
    } else if (navContainer) {
        navContainer.appendChild(btn);
    }

    // 탭 패널 생성
    const panel = document.createElement('div');
    panel.className = 'tab-pane';
    panel.id = id;
    panel.dataset.keyword = keyword;
    panel.dataset.start = String(start);

    panel.innerHTML = `<div class="search-panel-content">${htmlContent || getSkeletonHTML()}</div>`;

    const sentinel = document.createElement('div');
    sentinel.className = 'panel-sentinel';
    sentinel.textContent = '로딩...';

    const innerDiv = panel.querySelector('.search-panel-content');
    if (innerDiv) innerDiv.appendChild(sentinel);

    document.querySelector('.tabs-content').appendChild(panel);

    switchTab(id);
    setupInfiniteScrollForPanel(panel);
    return id;
}

function removeSearchTab(id) {
    // ... (removeSearchTab 함수 본문 유지) ...
    const btn = document.querySelector(`.tabs-nav [data-tab="${id}"]`);
    const panel = document.getElementById(id);
    if (btn) btn.remove();
    if (panel) {
        if (panelObservers.has(id)) { try { panelObservers.get(id).disconnect(); } catch (e) { } panelObservers.delete(id); }
        panel.remove();
    }
    const remainingTabs = document.querySelectorAll('.tabs-nav .tab-btn');
    const lastSearchTab = Array.from(remainingTabs).filter(t => t.id !== 'clippingsBtn').pop();

    if (lastSearchTab) {
        switchTab(lastSearchTab.dataset.tab);
    } else {
        switchTab('searchPanelsContainer');
    }
}

async function refreshSearchTab(id) {
    // ... (refreshSearchTab 함수 본문 유지) ...
    const panel = document.getElementById(id);
    if (!panel) return;
    const keyword = panel.dataset.keyword;
    const contentArea = panel.querySelector('.search-panel-content');

    // [추가] 새로고침 시작 시 로딩 메시지 및 스켈레톤 표시
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
        // [수정] 새로고침 성공 메시지
        showToast(`✅ '${keyword}' 검색 결과를 새로고침 완료했습니다.`);
    } catch (e) {
        console.error('새로고침 오류:', e);
        // [수정] 새로고침 오류 메시지
        showToast('❌ 새로고침 중 네트워크 오류가 발생했습니다.');
        if (contentArea) contentArea.innerHTML = '<div class="empty-state"><p>네트워크 오류로 새로고침에 실패했습니다.</p></div>';
    }
}

function switchTab(tabId) {
    // ... (switchTab 함수 본문 유지) ...
    if (!tabId) return;
    document.querySelectorAll('.tabs-nav .tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));

    const tabBtn = document.querySelector(`.tabs-nav [data-tab="${tabId}"]`);
    const panel = document.getElementById(tabId);
    if (tabBtn) tabBtn.classList.add('active');
    if (panel) panel.classList.add('active');

    const refreshBtn = document.getElementById('globalRefreshBtn');
    if (refreshBtn) {
        const isSearchTabActive = tabBtn && tabBtn.dataset.tab.startsWith('search-');
        refreshBtn.style.display = isSearchTabActive ? 'block' : 'none';
    }

    const hasSearchResults = !!document.querySelector('.tabs-nav button[data-tab^="search-"]');
    const initialMessage = document.getElementById('initialSearchMessage');
    if (initialMessage) {
        initialMessage.style.display = hasSearchResults ? 'none' : 'block';
    }
}

function setupInfiniteScrollForPanel(panel) {
    // ... (setupInfiniteScrollForPanel 함수 본문 유지) ...
    const sentinel = panel.querySelector('.panel-sentinel');
    if (!sentinel) return;

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
                    panelObservers.delete(panel.id);
                    loading = false;
                    return;
                }
                const html = await resp.text();
                if (!html || html.trim().length === 0) {
                    sentinel.textContent = '더 이상 결과가 없습니다';
                    observer.disconnect();
                    panelObservers.delete(panel.id);
                    loading = false;
                    return;
                }
                sentinel.insertAdjacentHTML('beforebegin', html);
                panel.dataset.start = String(start + 20);
                loading = false;
            } catch (err) {
                sentinel.textContent = '네트워크 오류';
                observer.disconnect();
                panelObservers.delete(panel.id);
                loading = false;
            }
        }
    }, { root: null, rootMargin: '200px' });

    observer.observe(sentinel);
    panelObservers.set(panel.id, observer);
}

async function handleSearch() {
    // ... (handleSearch 함수 본문 유지) ...
    const input = document.getElementById('keyword');
    if (!input) return;
    const keyword = input.value.trim();
    if (!keyword) {
        showToast('검색어를 입력하세요.');
        return;
    }
    saveRecentKeyword(keyword);
    const el = document.getElementById('recentKeywords');
    if (el) el.classList.remove('show');

    const existingTab = Array.from(document.querySelectorAll('.tab-pane')).find(p => p.dataset.keyword === keyword);
    if (existingTab) {
        switchTab(existingTab.id);
        showToast(`'${keyword}' 탭으로 이동했습니다.`);
        input.value = '';
        return;
    }

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


// ⭐⭐ [수정] 6. 클리핑 관련 로직 (loadClippingsTab 함수를 전역으로 정의) ⭐⭐
window.loadClippingsTab = async function () {
    const clippingsPane = document.getElementById('clippings');
    if (!clippingsPane) return;

    let innerContainer = clippingsPane.querySelector('.tab-content-inner');
    if (!innerContainer) { // innerContainer가 없으면 생성
        innerContainer = document.createElement('div');
        innerContainer.className = 'tab-content-inner';
        clippingsPane.appendChild(innerContainer);
    }
    innerContainer.innerHTML = '클리핑을 로드하는 중...'; // 로딩 표시

    try {
        const resp = await fetch('/clippings-tab');
        const html = await resp.text();

        const template = document.createElement('template');
        template.innerHTML = html;

        const scriptEl = template.content.querySelector('script');
        if (scriptEl) { scriptEl.remove(); } // 스크립트 제거 (main.js가 함수를 관리)

        innerContainer.innerHTML = template.innerHTML; // HTML 내용 삽입

        // ⭐⭐ 핵심 초기화: 전역 변수의 내용을 TextArea에 반영 ⭐⭐
        const textArea = document.getElementById('clippingTextArea');
        if (textArea) {
            textArea.value = clippedTextContent;
        }

        if (scriptEl) { // 동적으로 삽입된 HTML 내 스크립트 재실행
            const newScript = document.createElement('script');
            newScript.textContent = scriptEl.textContent;
            innerContainer.appendChild(newScript);
        }

    } catch (e) {
        console.error('클리핑 로드 실패', e);
        innerContainer.innerHTML = '<p class="empty-state">클리핑 로드 실패.</p>';
    }
}
// ⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐


async function deleteClip(clipId) {
    // ... (deleteClip 함수 본문 유지) ...
    if (!confirm('정말 삭제하시겠습니까?')) return;
    try {
        const resp = await fetch('/api/clip/' + clipId, { method: 'DELETE' });
        const j = await resp.json();
        if (j.success) {
            showToast('클리핑이 삭제되었습니다.');
            loadClippingsTab();
        } else {
            showToast('삭제에 실패했습니다.');
        }
    } catch (e) { showToast('삭제 요청 실패'); }
}
window.deleteClip = deleteClip;

async function deleteAllClips() {
    // ... (deleteAllClips 함수 본문 유지) ...
    if (!confirm('정말 모든 클리핑을 삭제하시겠습니까?')) return;
    try {
        clippedTextContent = defaultClippedText;
        localStorage.setItem('clippedTextContent', defaultClippedText); // 로컬 스토리지 업데이트
        const textArea = document.getElementById('clippingTextArea');
        if (textArea) textArea.value = defaultClippedText;
        const resp = await fetch('/api/clips/all', { method: 'DELETE' });
        const j = await resp.json();
        if (j.success) {
            showToast('모든 클리핑이 삭제되었습니다.');
            loadClippingsTab();
        }
    } catch (e) { showToast('삭제 요청 실패'); }
}
window.deleteAllClips = deleteAllClips;

async function clipArticleFromData(title, url, content, source, pubDate, originalLink, btnEl = null) {
    // ... (clipArticleFromData 함수 본문 유지) ...
    const fd = new FormData();
    fd.append('title', title);
    fd.append('url', url);
    fd.append('content', content || '');
    // ⭐⭐ [수정]: 백엔드로 메타데이터 전송 (main.py 수정 필요) ⭐⭐
    fd.append('source', source || '');
    fd.append('pubDate', pubDate || '');
    fd.append('originalLink', originalLink || url);
    // ⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐

    try {
        const r = await fetch('/api/clip', { method: 'POST', body: fd });
        const j = await r.json();
        if (j.success) {
            const date = new Date(pubDate);
            const formattedDate = !isNaN(date)
                ? `${date.getFullYear()}. ${date.getMonth() + 1}. ${date.getDate()}`
                : '';
            // pubDate와 originalLink를 사용하여 텍스트 구성
            const textToAdd = `▷ ${source} : ${title} (${formattedDate})\n${originalLink}\n`;

            clippedTextContent += textToAdd;
            localStorage.setItem('clippedTextContent', clippedTextContent); // 로컬 스토리지 업데이트
            const textArea = document.getElementById('clippingTextArea');
            if (textArea) textArea.value = clippedTextContent;

            // [추가] 클립보드에 텍스트 복사
            await navigator.clipboard.writeText(clippedTextContent);

            showToast('클립이 저장되었으며 텍스트가 클립보드에 복사되었습니다.');
            if (btnEl) {
                btnEl.textContent = '✓ 클립됨';
                btnEl.classList.add('clipped');
                btnEl.disabled = true;
            }
            // 같은 URL 가진 다른 버튼도 상태 변경 (생략)
            const otherBtn = document.querySelector(`.news-item[data-link="${escapeAttr(url)}"] .btn-clip`);
            if (otherBtn && otherBtn !== btnEl) {
                otherBtn.textContent = '✓ 클립됨';
                otherBtn.classList.add('clipped');
                otherBtn.disabled = true;
            }
        } else {
            showToast('저장 실패: ' + (j.message || ''));
        }
    } catch (e) { showToast('클립 요청 실패'); }
}

window.clipArticleFromEl = function (btnEl) {
    const item = (btnEl && btnEl.closest) ? btnEl.closest('.news-item') : null;
    if (!item) return;
    const d = item.dataset;
    // ⭐⭐ [수정]: 모든 메타데이터 (source, pubdate, originallink) 전달 ⭐⭐
    return clipArticleFromData(d.title, d.link, d.desc, d.source || d.domain, d.pubdate, d.origin || d.link, btnEl);
};


// 7. 모달 관련 (이전과 동일)
const modal = document.getElementById('detailModal');
const modalTitle = document.getElementById('modalTitle');
const modalBody = document.getElementById('modalBody');

async function showArticleDetailFromEl(itemEl) {
    // ... (showArticleDetailFromEl 함수 본문 유지) ...
    if (!itemEl) return;
    modalTitle.textContent = itemEl.dataset.title;
    modalBody.innerHTML = `<div class="skeleton skeleton-text" style="height: 200px;"></div>`;
    modal.classList.add('active');

    const clipBtn = modal.querySelector('.btn-primary');
    Object.keys(itemEl.dataset).forEach(key => {
        clipBtn.dataset[key] = itemEl.dataset[key];
    });

    const fd = new FormData();
    fd.append('url', itemEl.dataset.link);
    fd.append('title', itemEl.dataset.title);

    const resp = await fetch('/article-detail', { method: 'POST', body: fd });
    modalBody.innerHTML = await resp.text();
    clipBtn.dataset.content = modalBody.textContent.trim().slice(0, 500);
}

function closeModal() {
    // ... (closeModal 함수 본문 유지) ...
    modal.classList.remove('active');
}

function clipFromModal() {
    // ... (clipFromModal 함수 본문 유지) ...
    const btn = modal.querySelector('.btn-primary');
    clipArticleFromData(
        btn.dataset.title,
        btn.dataset.link,
        btn.dataset.content,
        btn.dataset.source,
        btn.dataset.pubdate,
        btn.dataset.originallink,
        btn
    );
}

// 8. 초기화 (DOMContentLoaded)
document.addEventListener('DOMContentLoaded', () => {
    // ... (DOMContentLoaded 함수 본문 유지) ...
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
            setTimeout(() => { recentKeywords.classList.remove('show'); }, 200);
        });
    }

    const tabsNav = document.querySelector('.tabs-nav');
    if (tabsNav) {
        tabsNav.addEventListener('click', (e) => {
            const btn = e.target.closest('button[data-tab]');
            if (!btn) return;
            const tabId = btn.dataset.tab;
            if (tabId === 'clippings') loadClippingsTab();
            switchTab(tabId); // 새로고침 없이 탭 전환만 수행
        });
    }

    const globalRefreshBtn = document.getElementById('globalRefreshBtn');
    if (globalRefreshBtn) {
        globalRefreshBtn.addEventListener('click', () => {
            const activeTab = document.querySelector('.tab-pane.active');
            if (activeTab && activeTab.dataset.tab.startsWith('search-')) {
                refreshSearchTab(activeTab.dataset.tab);
            }
        });
    }

    // 페이지 로드 시 기본 검색 실행
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
                    createSearchTab(kw, html, 21);
                }
            } catch (e) {
                console.error('기본 검색 오류:', e);
            }
        }
    }

    // 여기서 await 없이 호출해야 하므로 .then()을 사용합니다.
    loadDefaultSearch().then(() => {
        const firstSearchTab = document.querySelector('.tabs-nav button[data-tab^="search-"]');
        if (firstSearchTab) switchTab(firstSearchTab.dataset.tab);
    });

    // 키보드 이벤트
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            if (modal.classList.contains('active')) {
                closeModal();
            } else if (document.activeElement === input) {
                input.blur();
            }
        }
    });
    // ==========================================
    // ▼▼▼ 다크모드 코드 추가된 부분 ▼▼▼
    // ==========================================

    // [추가] 다크모드 토글 함수 (전역 접근 가능하게 window에 할당)
    window.toggleTheme = function () {
        document.body.classList.toggle('dark-mode');
        const isDark = document.body.classList.contains('dark-mode');
        localStorage.setItem('theme', isDark ? 'dark' : 'light');

        const btn = document.querySelector('.theme-btn');
        if (btn) btn.textContent = isDark ? '☀️' : '🌙';
    };

    // [추가] 페이지 로드 시 저장된 테마 불러오기
    const savedTheme = localStorage.getItem('theme');
    if (savedTheme === 'dark') {
        document.body.classList.add('dark-mode');
        const btn = document.querySelector('.theme-btn');
        if (btn) btn.textContent = '☀️';
    }
});