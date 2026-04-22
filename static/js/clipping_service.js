/**
 * clipping_service.js
 * 
 * Logic for categorized clipping, intelligent insertion, 
 * and managing the clippings tab text area.
 */

document.addEventListener('DOMContentLoaded', () => {
    // Migration for v1.2: Rename '■ 기타 관련' to '■ 기타' in local storage
    const storedText = localStorage.getItem('clippedTextContent');
    if (storedText && storedText.includes('■ 기타 관련')) {
        const updatedText = storedText.replace(/■ 기타 관련/g, '■ 기타');
        localStorage.setItem('clippedTextContent', updatedText);
        // If textArea is already on page (legacy fallback)
        const textArea = document.getElementById('clippingTextArea');
        if (textArea) textArea.value = updatedText;
        if (window.clippingEditor) window.clippingEditor.setMarkdown(updatedText);
    }
});

// Global reference to the editor instance
window.clippingEditor = null;

// Default text for the clipping memo pad
const DEFAULT_CLIPPED_TEXT = '■ 위원회 관련\n\n■ 방송·통신 관련\n\n■ 유관기관 관련\n\n■ 기타\n\n';

/**
 * Clips an article to the text area, categorized by section.
 */
function clipArticleFromData(title, link, content, source, pubDate, originalLink, btnEl, category) {
    let currentText = window.clippingEditor 
        ? window.clippingEditor.getMarkdown() 
        : (localStorage.getItem('clippedTextContent') || DEFAULT_CLIPPED_TEXT);

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
    const newEntry = `▷ ${source} : ${title} (${formattedDate})\n${originalLink}`;

    // Categorized Insertion Logic
    if (category) {
        const coreCategory = category.split(' ')[0];
        const lines = currentText.split('\n');
        let headerIndex = -1;

        for (let i = 0; i < lines.length; i++) {
            const trimmedLine = lines[i].trim();
            if (trimmedLine.startsWith('■') && trimmedLine.includes(coreCategory)) {
                headerIndex = i;
                break;
            }
        }

        if (headerIndex !== -1) {
            let insertAt = headerIndex + 1;
            while (insertAt < lines.length && lines[insertAt].trim() === '') {
                insertAt++;
            }
            while (insertAt < lines.length) {
                const line = lines[insertAt].trim();
                if (line.startsWith('■')) break;
                insertAt++;
            }
            let targetInsert = insertAt;
            while (targetInsert > headerIndex + 1 && lines[targetInsert - 1].trim() === '') {
                targetInsert--;
            }

            lines.splice(targetInsert, 0, newEntry);
            currentText = lines.join('\n');
        } else {
            currentText = currentText.trimEnd() + `\n\n■ ${category}\n${newEntry}\n`;
        }
    } else {
        currentText = currentText.trimEnd() + `\n\n${newEntry}\n`;
    }

    localStorage.setItem('clippedTextContent', currentText);

    if (window.clippingEditor) {
        window.clippingEditor.setMarkdown(currentText);
        // Optionally scroll to bottom but usually editor takes care of itself or requires explicit UI DOM manipulation
    } else {
        const textArea = document.getElementById('clippingTextArea');
        if (textArea) {
            textArea.value = currentText;
            textArea.scrollTop = textArea.scrollHeight;
        }
    }

    if (window.showToast) window.showToast(`✅ [${category}]에 추가되었습니다.`);

    if (btnEl) {
        const originalText = btnEl.textContent;
        btnEl.textContent = '저장됨!';
        btnEl.disabled = true;
        btnEl.classList.add('btn-success');
        setTimeout(() => {
            btnEl.textContent = originalText;
            btnEl.disabled = false;
            btnEl.classList.remove('btn-success');
        }, 2000);
    }
}
window.clipArticleFromData = clipArticleFromData;

/**
 * Toggles the category selection popup menu.
 */
function toggleClipMenu(btn) {
    const wrapper = btn.closest('.clip-selector-wrapper');
    const menu = wrapper.querySelector('.clip-popup-menu');
    document.querySelectorAll('.clip-popup-menu.show').forEach(m => {
        if (m !== menu) m.classList.remove('show');
    });
    menu.classList.toggle('show');
}
window.toggleClipMenu = toggleClipMenu;

// Close menus when clicking outside
document.addEventListener('click', (e) => {
    if (!e.target.closest('.clip-selector-wrapper')) {
        document.querySelectorAll('.clip-popup-menu.show').forEach(m => m.classList.remove('show'));
    }
});

/**
 * Loads the clippings tab content and initializes the text area.
 */
async function loadClippingsTab() {
    const clippingsPane = document.getElementById('clippings');
    if (!clippingsPane) return;

    let innerContainer = clippingsPane.querySelector('.tab-content-inner');
    if (!innerContainer) {
        innerContainer = document.createElement('div');
        innerContainer.className = 'tab-content-inner';
        clippingsPane.appendChild(innerContainer);
    }

    const hasContent = innerContainer.querySelector('#editor');
    if (hasContent && window.clippingEditor) return;

    innerContainer.innerHTML = '<div class="loading-state">클리핑을 로드하는 중...</div>';

    try {
        const resp = await fetch('/clippings-tab');
        const html = await resp.text();
        innerContainer.innerHTML = html;
        if (typeof renderActiveAlerts === 'function') renderActiveAlerts();

        const editorContainer = document.getElementById('editor');
        if (editorContainer) {
            const savedText = localStorage.getItem('clippedTextContent') || DEFAULT_CLIPPED_TEXT;
            const isDark = document.body.classList.contains('dark-mode');
            
            // Fix container overflow so dropdowns aren't clipped
            const wrapper = document.querySelector('.clipping-text-wrapper');
            if (wrapper) wrapper.style.overflow = 'visible';

            window.clippingEditor = new toastui.Editor({
                el: editorContainer,
                height: '600px',
                initialEditType: 'wysiwyg',
                previewStyle: 'vertical',
                theme: isDark ? 'dark' : '',
                initialValue: savedText,
                toolbarItems: [
                    ['heading', 'bold', 'italic', 'strike'],
                    ['hr', 'quote'],
                    ['ul', 'ol', 'task', 'indent', 'outdent'],
                    ['table', 'image', 'link'],
                    ['code', 'codeblock']
                ],
                events: {
                    change: () => {
                        localStorage.setItem('clippedTextContent', window.clippingEditor.getMarkdown());
                    }
                }
            });
        }

        const copyBtn = document.getElementById('copyTextBtn');
        if (copyBtn) {
            copyBtn.addEventListener('click', () => {
                const textToCopy = window.clippingEditor ? window.clippingEditor.getMarkdown() : '';
                if (!textToCopy) return;
                if (navigator.clipboard && window.isSecureContext) {
                    navigator.clipboard.writeText(textToCopy)
                        .then(() => window.showToast('📋 클리핑 텍스트가 복사되었습니다.'))
                        .catch(err => {
                            console.error('복사 실패:', err);
                            window.showToast('복사에 실패했습니다.');
                        });
                } else {
                    // Fallback using older method if needed
                    const temp = document.createElement('textarea');
                    temp.value = textToCopy;
                    document.body.appendChild(temp);
                    temp.select();
                    try {
                        document.execCommand('copy');
                        window.showToast('📋 클리핑 텍스트가 복사되었습니다.');
                    } catch (e) {
                        alert('복사에 실패했습니다.');
                    }
                    document.body.removeChild(temp);
                }
            });
        }

        const clearBtn = document.getElementById('clearTextBtn');
        if (clearBtn) {
            clearBtn.addEventListener('click', () => {
                if (window.clippingEditor) {
                    window.clippingEditor.setMarkdown(DEFAULT_CLIPPED_TEXT);
                    localStorage.setItem('clippedTextContent', DEFAULT_CLIPPED_TEXT);
                    window.showToast('✨ 텍스트를 초기화했습니다.');
                }
            });
        }

        const clearAllAlertsBtn = document.getElementById('clearAllAlertsBtn');
        if (clearAllAlertsBtn && typeof window.clearAllAlerts === 'function') {
            clearAllAlertsBtn.addEventListener('click', window.clearAllAlerts);
        }

        // Removed initResizeHandle() since TOAST UI has its own sizing logic
    } catch (e) {
        console.error('클리핑 탭 로드 실패:', e);
        innerContainer.innerHTML = '<div class="error-state">클리핑 탭을 불러오는데 실패했습니다.</div>';
    }
}
window.loadClippingsTab = loadClippingsTab;

/**
 * Legacy resize logic removed for TOAST UI Integration
 */
