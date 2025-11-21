// localStorage 키
const CLIPS_STORAGE_KEY = 'navernews_clips';

// localStorage에서 클립 로드
function getClipsFromStorage() {
    const data = localStorage.getItem(CLIPS_STORAGE_KEY);
    return data ? JSON.parse(data) : {};
}

// localStorage에 클립 저장
function saveClipsToStorage(clips) {
    localStorage.setItem(CLIPS_STORAGE_KEY, JSON.stringify(clips));
}

function escapeHtml(s) { return String(s || '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }
function escapeAttr(s) { return (s || '').replace(/"/g, '&quot;').replace(/'/g, '&#39;'); }

let searchTabCounter = 0;
const panelObservers = new Map();
const defaultClippedText = '■ 위원회 관련\n\n■ 방송·통신 관련\n\n■ 유관기관 관련\n\n■ 기타 관련\n\n';
let clippedTextContent = defaultClippedText; // 클리핑 텍스트를 저장할 전역 변수

// 토스트 알림 함수
function showToast(message) {
    const container = document.getElementById('toastContainer');
    if (!container) return;
    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.textContent = message;
    container.appendChild(toast);

    setTimeout(() => {
        toast.classList.add('show');
    }, 10);

    setTimeout(() => {
        toast.remove();
    }, 3000); // 3초 후 사라짐
}
window.showToast = showToast;

// --- Dark Mode Logic ---
function initTheme() {
    const savedTheme = localStorage.getItem('theme');
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;

    if (savedTheme === 'dark' || (!savedTheme && prefersDark)) {
        document.body.classList.add('dark-mode');
        updateThemeBtn('🌙'); // Moon icon
    } else {
        document.body.classList.remove('dark-mode');
        updateThemeBtn('☀️'); // Sun icon
    }
}

function toggleTheme() {
    document.body.classList.toggle('dark-mode');
    const isDark = document.body.classList.contains('dark-mode');
    localStorage.setItem('theme', isDark ? 'dark' : 'light');
    updateThemeBtn(isDark ? '🌙' : '☀️');
}

function updateThemeBtn(icon) {
    const btn = document.getElementById('themeToggle');
    if (btn) btn.textContent = icon;
}

// --- Skeleton Loading ---
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
        <div class="skeleton-card">
            <div class="skeleton skeleton-title"></div>
            <div class="skeleton skeleton-text"></div>
            <div class="skeleton skeleton-text short"></div>
        </div>
    `;
}

function createSearchTab(keyword, htmlContent, start = 1) {
    const id = 'search-' + (++searchTabCounter) + '-' + Date.now().toString(36);
    // 버튼
    const btn = document.createElement('button');
    btn.className = 'tab-btn';
    btn.dataset.tab = id;
    btn.textContent = keyword.length > 20 ? keyword.slice(0, 17) + '…' : keyword;

    const close = document.createElement('span'); close.textContent = ' ×'; close.style.marginLeft = '8px';
    close.onclick = (e) => {
        e.stopPropagation();
        removeSearchTab(id);
    };
    btn.appendChild(close);

    // 새로고침 버튼 앞에 탭을 추가하여 항상 오른쪽 끝에 있도록 보장
    const navContainer = document.querySelector('.tabs-nav');
    const refreshBtn = document.getElementById('globalRefreshBtn');
    if (navContainer && refreshBtn) {
        navContainer.insertBefore(btn, refreshBtn);
    } else if (navContainer) {
        navContainer.appendChild(btn); // Fallback
    }

    // 패널
    const panel = document.createElement('div');
    panel.className = 'tab-pane';
    panel.id = id;
    panel.dataset.keyword = keyword;
    panel.dataset.start = String(start);

    // Initial Skeleton
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
        // 남은 검색 탭이 없으면 초기 메시지 화면을 보여줍니다.
        switchTab('searchPanelsContainer');
    }
}

async function refreshSearchTab(id) {
    const panel = document.getElementById(id);

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
        showToast(`'${keyword}' 검색 결과를 새로고침했습니다.`);
    } catch (e) {
        console.error('새로고침 오류:', e);
        showToast('새로고침 중 네트워크 오류가 발생했습니다.');
    }
}

function switchTab(tabId) {
    if (!tabId) return;

    // 모든 탭 버튼 비활성화
    document.querySelectorAll('.tabs-nav .tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));

    // 선택된 탭 버튼과 패널 활성화
    const tabBtn = document.querySelector(`.tabs-nav [data-tab="${tabId}"]`);
    const panel = document.getElementById(tabId);
    if (tabBtn) tabBtn.classList.add('active');
    if (panel) panel.classList.add('active');

    // 새로고침 버튼 표시/숨김 로직
    const refreshBtn = document.getElementById('globalRefreshBtn');
    if (refreshBtn) {
        // 활성화된 탭이 검색 결과 탭일 경우에만 새로고침 버튼 표시
        const isSearchTabActive = tabBtn && tabBtn.dataset.tab.startsWith('search-');
        refreshBtn.style.display = isSearchTabActive ? 'block' : 'none';
    }


    // 검색 결과가 하나라도 있으면 초기 메시지 숨기기
    const hasSearchResults = !!document.querySelector('.tabs-nav button[data-tab^="search-"]');
    const initialMessage = document.getElementById('initialSearchMessage');
    if (initialMessage) {
        initialMessage.style.display = hasSearchResults ? 'none' : 'block';
    }
}

function setupInfiniteScrollForPanel(panel) {
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
            console.log('[INFINITE] Sentinel reached for', panel.id);

            const keyword = panel.dataset.keyword;
            let start = parseInt(panel.dataset.start || '1', 10);

            console.log('[INFINITE] Loading keyword:', keyword, 'start:', start);

            const fd = new FormData();
            fd.append('keyword', keyword);
            fd.append('start', start);

            try {
                const resp = await fetch('/search-results', { method: 'POST', body: fd });
                console.log('[INFINITE] Response status:', resp.status);

                if (!resp.ok) {
                    console.error('[INFINITE] Load failed', resp.status);
                    sentinel.textContent = '추가 로드 실패 (상태: ' + resp.status + ')';
                    observer.disconnect();
                    panelObservers.delete(panel.id);
                    loading = false;
                    return;
                }

                const html = await resp.text();
                console.log('[INFINITE] Loaded HTML length:', html.length);

                if (!html || html.trim().length === 0) {
                    console.log('[INFINITE] No more results');
                    sentinel.textContent = '더 이상 결과가 없습니다';
                    observer.disconnect();
                    panelObservers.delete(panel.id);
                    loading = false;
                    return;
                }

                // sentinel 앞에 콘텐츠 삽입
                sentinel.insertAdjacentHTML('beforebegin', html);

                // start 업데이트
                panel.dataset.start = String(start + 20);
                console.log('[INFINITE] Updated start to:', start + 20);

                loading = false;

            } catch (err) {
                console.error('[INFINITE] Error:', err);
                sentinel.textContent = '네트워크 오류';
                observer.disconnect();
                panelObservers.delete(panel.id);
                loading = false;
            }
        }
    }, {
        root: null,  // viewport 기준
        rootMargin: '200px'  // 200px 전에 미리 감지
    });

    observer.observe(sentinel);
    panelObservers.set(panel.id, observer);
    console.log('[INFINITE] Observer setup for', panel.id);
}

window.handleSearch = handleSearch; // 기존 코드와 호환

// 클리핑 탭 동적 로드
async function loadClippingsTab() {
    try {
        const resp = await fetch('/clippings-tab');
        const html = await resp.text();
        const clippingsPane = document.getElementById('clippings');
        if (!clippingsPane) return;

        // 패딩을 위한 내부 컨테이너를 찾거나 생성합니다.
        let innerContainer = clippingsPane.querySelector('.tab-content-inner');

        // 1. 스크립트를 제외한 HTML을 먼저 삽입합니다.
        const template = document.createElement('template');
        template.innerHTML = html;
        const scriptEl = template.content.querySelector('script');
        if (scriptEl) { scriptEl.remove(); }
        innerContainer.innerHTML = template.innerHTML;

        // 탭이 로드된 후, 전역 변수에 저장된 텍스트를 textarea에 복원합니다.
        const textArea = document.getElementById('clippingTextArea');
        if (textArea) textArea.value = clippedTextContent;

        // 2. 분리했던 스크립트를 DOM에 추가하여 실행시킵니다.
        if (scriptEl) {
            const newScript = document.createElement('script');
            newScript.textContent = scriptEl.textContent; // 스크립트 내용 복사
            innerContainer.appendChild(newScript);
        }
    } catch (e) {
        console.error('클리핑 로드 실패', e);
    }
}

// 클리핑 삭제 (전역 함수 — 클리핑_tab.html의 버튼에서 호출)
async function deleteClip(clipId) {
    if (!confirm('정말 삭제하시겠습니까?')) return;
    try {
        const resp = await fetch('/api/clip/' + clipId, { method: 'DELETE' });
        const j = await resp.json();
        if (j.success) {
            showToast('클리핑이 삭제되었습니다.');
            loadClippingsTab(); // 재로드
        } else {
            showToast('삭제에 실패했습니다.');
        }
    } catch (e) {
        console.error(e);
        showToast('삭제 요청 실패');
    }
}
window.deleteClip = deleteClip;

// 모든 클리핑 삭제
async function deleteAllClips() {
    if (!confirm('정말 모든 클리핑을 삭제하시겠습니까?')) return;
    try {
        // UI 즉시 반영
        clippedTextContent = defaultClippedText;
        const textArea = document.getElementById('clippingTextArea');
        if (textArea) textArea.value = defaultClippedText;

        const resp = await fetch('/api/clips/all', { method: 'DELETE' });
        const j = await resp.json();
        if (j.success) {
            showToast('모든 클리핑이 삭제되었습니다.');
            loadClippingsTab();
        }
    } catch (e) {
        console.error(e);
        showToast('삭제 요청 실패');
    }
}
window.deleteAllClips = deleteAllClips;

async function clipArticleFromData(title, url, content, source, pubDate, originalLink, btnEl = null) {
    console.log('[CLIP] 저장 시도:', { title, url, content, source, pubDate, originalLink });
    const fd = new FormData();
    fd.append('title', title);
    fd.append('url', url);
    fd.append('content', content || '');
    try {
        const r = await fetch('/api/clip', { method: 'POST', body: fd });
        const j = await r.json();
        console.log('[CLIP] 응답:', j);
        if (j.success) {
            const date = new Date(pubDate);
            const formattedDate = !isNaN(date)
                ? `${date.getFullYear()}. ${date.getMonth() + 1}. ${date.getDate()}`
                : '';
            const textToAdd = `▷ ${source} : ${title} (${formattedDate})\n${originalLink}\n`;

            // 1. 전역 변수에 텍스트를 누적합니다.
            clippedTextContent += textToAdd;

            // 2. 만약 클리핑 탭이 현재 활성화되어 있다면, textarea의 값을 즉시 업데이트합니다.
            const textArea = document.getElementById('clippingTextArea');
            if (textArea) textArea.value = clippedTextContent;

            showToast('클립이 저장되었습니다.');

            // 버튼 상태 변경
            if (btnEl) {
                btnEl.textContent = '✓ 클립됨';
                btnEl.classList.add('clipped');
                btnEl.disabled = true;
            }

            // 추가: URL을 기반으로 목록에 있는 다른 버튼도 업데이트
            const otherBtn = document.querySelector(`.news-item[data-link="${escapeAttr(url)}"] .btn-clip`);
            if (otherBtn && otherBtn !== btnEl) {
                otherBtn.textContent = '✓ 클립됨';
                otherBtn.classList.add('clipped');
                otherBtn.disabled = true;
            }

        } else {
            showToast('클립 저장에 실패했습니다: ' + (j.message || ''));
        }
    } catch (e) {
        console.error('[CLIP] 요청 실패:', e);
        showToast('클립 요청 실패');
    }
}

window.clipArticleFromEl = function (btnEl) {
    const item = (btnEl && btnEl.closest) ? btnEl.closest('.news-item') : null;
    const title = item?.dataset?.title || '';
    const url = item?.dataset?.link || '';
    const content = item?.dataset?.desc || '';
    const source = item?.dataset?.source || item?.dataset?.domain || '';
    const pubDate = item?.dataset?.pubdate || '';
    const originalLink = item?.dataset?.origin || url;
    return clipArticleFromData(title, url, content, source, pubDate, originalLink, btnEl);
};

// 모달 관련 함수
const modal = document.getElementById('detailModal');
const modalTitle = document.getElementById('modalTitle');
const modalBody = document.getElementById('modalBody');

async function showArticleDetailFromEl(itemEl) {
    if (!itemEl) return;

    modalTitle.textContent = itemEl.dataset.title;

    modalBody.innerHTML = `
        <div class="skeleton skeleton-title" style="width: 100%; height: 30px; margin-bottom: 20px;"></div>
        <div class="skeleton skeleton-text" style="height: 200px;"></div>
    `;
    modal.classList.add('active');

    // 모달의 클리핑 버튼에 데이터 설정
    const clipBtn = modal.querySelector('.btn-primary');
    Object.keys(itemEl.dataset).forEach(key => {
        clipBtn.dataset[key] = itemEl.dataset[key];
    });

    const fd = new FormData();
    fd.append('url', itemEl.dataset.link);
    fd.append('title', itemEl.dataset.title); // 'title' 필드 추가

    const resp = await fetch('/article-detail', { method: 'POST', body: fd });
    modalBody.innerHTML = await resp.text();
    clipBtn.dataset.content = modalBody.textContent.trim().slice(0, 500); // 파싱된 본문 일부 저장
}

function closeModal() {
    modal.classList.remove('active');
}

function clipFromModal() {
    const btn = modal.querySelector('.btn-primary');
    clipArticleFromData(
        btn.dataset.title,
        btn.dataset.url,
        btn.dataset.content,
        btn.dataset.source,
        btn.dataset.pubdate,
        btn.dataset.originallink,
        btn // 모달의 클립 버튼도 상태 변경
    );
}

document.addEventListener('DOMContentLoaded', () => {
    const searchBtn = document.getElementById('searchBtn');
    const input = document.getElementById('keyword');
    if (searchBtn) searchBtn.addEventListener('click', handleSearch);
    if (input) input.addEventListener('keypress', (e) => { if (e.key === 'Enter') handleSearch(); });

    const tabsNav = document.querySelector('.tabs-nav');
    if (tabsNav) {
        tabsNav.addEventListener('click', (e) => {
            const btn = e.target.closest('button[data-tab]');
            if (!btn) return;
            const tabId = btn.dataset.tab;
            if (tabId === 'clippings') {
                loadClippingsTab(); // 클리핑 탭을 누를 때마다 목록을 새로고침하고 텍스트를 복원합니다.
            }
            if (activeTab && activeTab.dataset.tab.startsWith('search-')) {
                refreshSearchTab(activeTab.dataset.tab);
            }
        });
    }
    // ===== 페이지 로드 시 기본 검색 =====
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
                    createSearchTab(kw, html, 21); // 탭 생성 및 활성화는 함수 내부에서 처리
                }
            } catch (e) {
                console.error('기본 검색 오류:', e);
            }
        }
    }
    loadDefaultSearch().then(() => {
        // 기본 검색 로드 후, 첫 번째 검색 탭을 활성화합니다.
        const firstSearchTab = document.querySelector('.tabs-nav button[data-tab^="search-"]');
        if (firstSearchTab) switchTab(firstSearchTab.dataset.tab);
    });
    // --- Scroll to Top ---
    const scrollTopBtn = document.getElementById('scrollTopBtn');
    if (scrollTopBtn) {
        window.addEventListener('scroll', () => {
            if (window.scrollY > 300) {
                scrollTopBtn.classList.add('show');
            } else {
                scrollTopBtn.classList.remove('show');
            }
        });
        scrollTopBtn.addEventListener('click', () => {
            window.scrollTo({ top: 0, behavior: 'smooth' });
        });
    }

    // --- Keyboard Shortcuts ---
    document.addEventListener('keydown', (e) => {
        // '/' to focus search
        if (e.key === '/' && document.activeElement !== input) {
            e.preventDefault();
            input.focus();
        }
        // 'Esc' to close modal or clear search
        if (e.key === 'Escape') {
            if (modal.classList.contains('active')) {
                closeModal();
            } else if (document.activeElement === input) {
                input.blur();
            }
        }
    });

    // --- Theme Init ---
    const themeBtn = document.getElementById('themeToggle');
    if (themeBtn) themeBtn.addEventListener('click', toggleTheme);
    initTheme();
});