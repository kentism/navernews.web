(function () {
    'use strict';
    const ui = window.NewsUI;
    const doc = window.ClippingDocument;
    const storageKey = 'clippedTextContent';
    let text = ui.read(storageKey, doc.emptyText);
    let editor = null;
    let initializing = false;
    let persistent = true;
    let loading = null;

    function updateStatus() {
        const status = document.getElementById('clippingSaveStatus');
        if (!status) return;
        status.textContent = persistent ? '브라우저 저장 완료' : '브라우저 저장 실패 · 파일로 보관해주세요';
        status.classList.toggle('save-failed', !persistent);
    }
    function currentText() {
        if (editor) text = editor.getMarkdown();
        else {
            const area = document.getElementById('clippingTextArea');
            if (area) text = area.value;
        }
        return text;
    }
    function persist(value) {
        text = value;
        persistent = ui.write(storageKey, text);
        updateStatus();
    }
    function setText(value) {
        persist(value);
        if (editor) {
            initializing = true;
            try { editor.setMarkdown(value); } finally { initializing = false; }
        }
        const area = document.getElementById('clippingTextArea');
        if (area) area.value = value;
    }
    function clipArticles(items, category) {
        const result = doc.insertArticles(currentText(), items, category);
        if (result.added) setText(result.text);
        ui.toast(result.added ? `[${category || '기타'}] 기사 ${result.added}건을 추가했습니다.` : '이미 클리핑한 기사입니다.');
        return result.added;
    }
    window.clipArticles = clipArticles;
    window.clipArticleFromData = function (title, link, content, source, pubDate, originalLink, button, category) {
        title = window.NewsArticleTitles?.clippingTitle(button, title) ?? title;
        if (clipArticles([{ title, link, source, pubDate, originalLink }], category)) window.NewsMotion.success(button);
    };
    window.toggleClipMenu = function (button) {
        const menu = button.closest('.clip-selector-wrapper').querySelector('.clip-popup-menu');
        document.querySelectorAll('.clip-popup-menu.show').forEach(other => { if (other !== menu) other.classList.remove('show'); });
        menu.classList.toggle('show');
    };

    async function copy(includeUrls, button) {
        const value = window.ClippingCopyFormatter.formatClippingText(currentText(), { includeUrls });
        try {
            if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(value);
            else {
                const area = document.createElement('textarea');
                area.value = value;
                document.body.append(area);
                area.select();
                try { if (!document.execCommand('copy')) throw new Error('copy failed'); }
                finally { area.remove(); }
            }
            ui.toast(includeUrls ? '클리핑 텍스트를 복사했습니다.' : 'URL을 제외한 클리핑 텍스트를 복사했습니다.');
            window.NewsMotion.success(button);
        } catch (_) { ui.toast('복사하지 못했습니다. 파일 저장을 이용해주세요.'); }
    }

    async function loadClippingsTab() {
        if (document.getElementById('editor')) return;
        if (loading) return loading;
        loading = (async () => {
            const pane = document.querySelector('#clippings .tab-content-inner');
            try {
                const response = await ui.request('/clippings-tab');
                pane.innerHTML = await response.text();
                window.renderActiveAlerts?.();
                if (window.toastui?.Editor) {
                    initializing = true;
                    try {
                        editor = new window.toastui.Editor({
                            el: document.getElementById('editor'), height: '600px',
                            initialEditType: 'wysiwyg', previewStyle: 'vertical',
                            theme: document.body.classList.contains('dark-mode') ? 'dark' : '',
                            initialValue: text,
                            toolbarItems: [['heading', 'bold', 'italic', 'strike'], ['hr', 'quote'],
                                ['ul', 'ol', 'task'], ['table', 'link'], ['code', 'codeblock']],
                            events: { change: () => { if (!initializing && editor) persist(editor.getMarkdown()); } }
                        });
                        window.clippingEditor = editor;
                    } catch (_) { editor = null; }
                    finally { initializing = false; }
                }
                if (!editor) {
                    const area = document.createElement('textarea');
                    area.id = 'clippingTextArea';
                    area.className = 'clipping-plain-editor';
                    area.setAttribute('aria-label', '클리핑 편집');
                    area.value = text;
                    area.addEventListener('input', () => persist(area.value));
                    document.getElementById('editor').replaceChildren(area);
                }
                document.getElementById('copyTextBtn').addEventListener('click', event => copy(true, event.currentTarget));
                document.getElementById('copyTextWithoutUrlsBtn').addEventListener('click', event => copy(false, event.currentTarget));
                document.getElementById('downloadClippingBtn').addEventListener('click', () => {
                    const day = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Seoul' }).format(new Date());
                    ui.download(window.ClippingCopyFormatter.formatClippingText(currentText(), { includeUrls: true }), `clipping-${day}.txt`);
                });
                document.getElementById('clearTextBtn').addEventListener('click', () => {
                    if (confirm('작성 중인 클리핑을 비울까요? 필요한 내용은 먼저 파일로 보관해주세요.')) setText(doc.emptyText);
                });
                document.getElementById('clearAllAlertsBtn')?.addEventListener('click', () => window.clearAllAlerts());
                persist(text);
            } catch (error) {
                pane.replaceChildren();
                const message = document.createElement('p');
                message.textContent = error.message;
                const retry = document.createElement('button');
                retry.textContent = '다시 불러오기';
                retry.className = 'btn-small';
                retry.addEventListener('click', loadClippingsTab);
                pane.append(message, retry);
            } finally { loading = null; }
        })();
        return loading;
    }
    window.loadClippingsTab = loadClippingsTab;
    document.addEventListener('click', event => {
        if (!event.target.closest('.clip-selector-wrapper')) {
            document.querySelectorAll('.clip-popup-menu.show').forEach(menu => menu.classList.remove('show'));
        }
    });
}());
