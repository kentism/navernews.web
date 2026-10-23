(function (root) {
    'use strict';
    const LIMIT = 8;
    const STORAGE_KEY = 'navernews_home_keywords';

    /** Saved searches are browser-local; an explicit empty list never restores defaults. */
    function normalizeKeywords(items) {
        return [...new Set(items.filter(item => typeof item === 'string').map(item => item.trim())
            .filter(item => item && item.length <= 300))].slice(0, LIMIT);
    }
    function readKeywords(raw, defaults) {
        try {
            const saved = JSON.parse(raw);
            return normalizeKeywords(Array.isArray(saved) ? saved : defaults);
        } catch (_) { return normalizeKeywords(defaults); }
    }
    function changeKeyword(keywords, index, value) {
        const keyword = value.trim();
        let error = '';
        if (!keyword) error = '검색어를 입력해주세요.';
        else if (keyword.length > 300) error = '검색어는 300자 이내로 입력해주세요.';
        else if (keywords.some((item, i) => item === keyword && i !== index)) error = '이미 저장된 검색어입니다.';
        else if (index === keywords.length && keywords.length >= LIMIT) error = '검색어는 최대 8개까지 저장할 수 있습니다.';
        if (error) return { keywords, error };
        const next = [...keywords];
        next[index] = keyword;
        return { keywords: next, error: '' };
    }
    const addKeyword = (keywords, value) => changeKeyword(keywords, keywords.length, value);
    const renameKeyword = (keywords, index, value) => changeKeyword(keywords, index, value);
    if (typeof module !== 'undefined') module.exports = { readKeywords, normalizeKeywords, addKeyword, renameKeyword };
    if (typeof document === 'undefined') return;

    document.addEventListener('DOMContentLoaded', () => {
        const ui = root.NewsUI;
        const list = document.getElementById('homeKeywordList');
        let keywords = readKeywords(ui.read(STORAGE_KEY, null), root.defaultSearchKeywords || []);
        let searching = false;
        const form = document.getElementById('homeKeywordForm');
        const input = document.getElementById('homeKeywordInput');
        const batch = document.getElementById('searchSavedKeywordsBtn');
        const status = document.getElementById('homeKeywordsStatus');

        function save() {
            const stored = ui.write(STORAGE_KEY, JSON.stringify(keywords));
            status.textContent = stored ? '브라우저에 저장됨' : '저장 실패 · 새로고침하면 변경사항이 사라질 수 있습니다';
            status.classList.toggle('save-failed', !stored);
        }
        function updateCount() {
            document.getElementById('homeKeywordCount').textContent = `${keywords.length} / ${LIMIT}`;
            document.getElementById('batchSearchCount').textContent = keywords.length;
            batch.disabled = !keywords.length || searching;
            form.hidden = keywords.length >= LIMIT;
        }
        function tool(name, label, action) {
            const button = document.createElement('button');
            button.type = 'button'; button.className = 'icon-button';
            button.title = label; button.setAttribute('aria-label', label);
            button.append(ui.icon(name));
            button.addEventListener('click', action);
            return button;
        }
        function render() {
            list.replaceChildren();
            keywords.forEach((keyword, index) => {
                const row = document.createElement('li'); row.className = 'saved-keyword-row';
                const number = document.createElement('span'); number.className = 'keyword-number';
                number.textContent = String(index + 1).padStart(2, '0');
                const field = document.createElement('input');
                field.type = 'text'; field.value = keyword; field.maxLength = 300;
                field.setAttribute('aria-label', `${index + 1}번 저장 검색어`);
                field.addEventListener('change', () => {
                    const result = renameKeyword(keywords, index, field.value);
                    if (result.error) { field.value = keywords[index]; ui.toast(result.error); return; }
                    keywords = result.keywords; field.value = keywords[index]; save();
                });
                field.addEventListener('keydown', event => {
                    if (event.key === 'Enter' && !event.isComposing) { field.blur(); root.NewsSearch.openSearch(keywords[index]); }
                });
                const actions = document.createElement('div'); actions.className = 'keyword-row-actions';
                actions.append(tool('search', `${index + 1}번 검색어 검색`, () => root.NewsSearch.openSearch(keywords[index])),
                    tool('x', `${index + 1}번 검색어 삭제`, () => { keywords.splice(index, 1); save(); render(); }));
                row.append(number, field, actions); list.append(row);
            });
            document.getElementById('homeKeywordsEmpty').hidden = keywords.length > 0;
            updateCount();
        }
        form.addEventListener('submit', event => {
            event.preventDefault();
            const result = addKeyword(keywords, input.value);
            if (result.error) { ui.toast(result.error); return; }
            keywords = result.keywords; input.value = ''; save(); render();
            if (!form.hidden) input.focus();
        });
        batch.addEventListener('click', async () => {
            if (searching || !keywords.length) return;
            searching = true; updateCount(); batch.setAttribute('aria-busy', 'true');
            try { await root.NewsSearch.openMany([...keywords]); }
            finally { searching = false; updateCount(); batch.removeAttribute('aria-busy'); }
        });
        render(); save();
    });
}(typeof window !== 'undefined' ? window : {}));
