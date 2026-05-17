/**
 * clipping_service.js
 *
 * Handles the clipping editor, final clipping learning history, and the
 * visible learning/backup status panel in the clippings tab.
 */

const CLIPPED_TEXT_KEY = 'clippedTextContent';
const DEFAULT_CLIPPED_TEXT = '■ 위원회 관련\n\n■ 방송·통신 관련\n\n■ 유관기관 관련\n\n■ 기타\n\n';

window.clippingEditor = null;

document.addEventListener('DOMContentLoaded', () => {
    const storedText = localStorage.getItem(CLIPPED_TEXT_KEY);
    if (storedText) {
        persistClippedText(migrateClippedText(storedText));
    }
});

function migrateClippedText(text) {
    return String(text || '')
        .replace(/■\s*유관기관 관련/g, '■ 유관기관 관련')
        .replace(/■\s*기타 관련/g, '■ 기타')
        .replace(/▷/g, '▷');
}

function normalizeClipUrl(url) {
    return String(url || '')
        .trim()
        .replace(/\\([()[\]_*])/g, '$1');
}

function normalizeMarkdownUrls(text) {
    return String(text || '').replace(/(^|\n)(<?https?:\/\/[^\s>]+>?)(?=\n|$)/g, (match, prefix, url) => {
        const rawUrl = url.replace(/^<|>$/g, '');
        return `${prefix}<${normalizeClipUrl(rawUrl)}>`;
    });
}

function persistClippedText(text) {
    const normalizedText = normalizeMarkdownUrls(migrateClippedText(text));
    localStorage.setItem(CLIPPED_TEXT_KEY, normalizedText);
    return normalizedText;
}

function escapeHtml(value) {
    return String(value || '').replace(/[&<>"']/g, ch => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
    }[ch]));
}

function formatDateTime(value) {
    if (!value) return '-';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleString();
}

function showToast(message) {
    if (window.showToast) {
        window.showToast(message);
    }
}

function getCurrentClippingText() {
    if (window.clippingEditor) {
        return persistClippedText(window.clippingEditor.getMarkdown());
    }
    return normalizeMarkdownUrls(localStorage.getItem(CLIPPED_TEXT_KEY) || '');
}

function setEditorText(text) {
    const normalized = persistClippedText(text);
    if (window.clippingEditor) {
        window.clippingEditor.setMarkdown(normalized);
    }
    const textArea = document.getElementById('clippingTextArea');
    if (textArea) {
        textArea.value = normalized;
    }
}

function buildClippingEntry(title, link, source, pubDate, originalLink) {
    let formattedDate = '';
    if (pubDate) {
        const dateObj = new Date(pubDate);
        if (!Number.isNaN(dateObj.getTime())) {
            const month = String(dateObj.getMonth() + 1).padStart(2, '0');
            const day = String(dateObj.getDate()).padStart(2, '0');
            formattedDate = `${month}.${day}.`;
        }
    }

    const safeSource = source || '출처 미상';
    const safeOriginalLink = normalizeClipUrl(originalLink || link);
    const dateSuffix = formattedDate ? ` (${formattedDate})` : '';
    return `▷ ${safeSource} : ${title}${dateSuffix}\n<${safeOriginalLink}>`;
}

function insertEntryByCategory(currentText, category, entry) {
    const targetCategory = category || '기타';
    const coreCategory = targetCategory.split(' ')[0];
    const lines = (currentText || DEFAULT_CLIPPED_TEXT).split('\n');
    let headerIndex = -1;

    for (let i = 0; i < lines.length; i++) {
        const trimmedLine = lines[i].trim();
        if (trimmedLine.startsWith('■') && trimmedLine.includes(coreCategory)) {
            headerIndex = i;
            break;
        }
    }

    if (headerIndex === -1) {
        return `${currentText.trimEnd()}\n\n■ ${targetCategory}\n${entry}\n`;
    }

    let insertAt = headerIndex + 1;
    while (insertAt < lines.length) {
        const line = lines[insertAt].trim();
        if (line.startsWith('■')) break;
        insertAt++;
    }

    let targetInsert = insertAt;
    while (targetInsert > headerIndex + 1 && lines[targetInsert - 1].trim() === '') {
        targetInsert--;
    }

    lines.splice(targetInsert, 0, entry);
    return lines.join('\n');
}

function clipArticleFromData(title, link, content, source, pubDate, originalLink, btnEl, category, options = {}) {
    const currentText = window.clippingEditor
        ? window.clippingEditor.getMarkdown()
        : (localStorage.getItem(CLIPPED_TEXT_KEY) || DEFAULT_CLIPPED_TEXT);
    const targetCategory = category || '기타';
    const newEntry = buildClippingEntry(title, link, source, pubDate, originalLink);
    const nextText = insertEntryByCategory(currentText, targetCategory, newEntry);

    setEditorText(nextText);
    showToast(`[${targetCategory}] 클리핑에 추가했습니다.`);

    if (!options.skipRecord) {
        fetch('/api/clipping-events', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                title,
                link,
                original_link: originalLink || link,
                source,
                pub_date: pubDate,
                category: targetCategory
            })
        }).catch(err => console.warn('Failed to record clipping event:', err));
    }

    if (btnEl) {
        const originalText = btnEl.textContent;
        btnEl.textContent = '저장됨';
        btnEl.disabled = true;
        btnEl.classList.add('btn-success');
        setTimeout(() => {
            btnEl.textContent = originalText;
            btnEl.disabled = false;
            btnEl.classList.remove('btn-success');
        }, 1800);
    }
}
window.clipArticleFromData = clipArticleFromData;

function toggleClipMenu(btn) {
    const wrapper = btn.closest('.clip-selector-wrapper');
    const menu = wrapper.querySelector('.clip-popup-menu');
    document.querySelectorAll('.clip-popup-menu.show').forEach(openMenu => {
        if (openMenu !== menu) openMenu.classList.remove('show');
    });
    menu.classList.toggle('show');
}
window.toggleClipMenu = toggleClipMenu;

document.addEventListener('click', event => {
    if (!event.target.closest('.clip-selector-wrapper')) {
        document.querySelectorAll('.clip-popup-menu.show').forEach(menu => menu.classList.remove('show'));
    }
});

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
    if (hasContent && window.clippingEditor) {
        refreshLearningStatus();
        return;
    }

    innerContainer.innerHTML = '<div class="loading-state">클리핑을 불러오는 중...</div>';

    try {
        const resp = await fetch('/clippings-tab');
        const html = await resp.text();
        innerContainer.innerHTML = html;
        if (typeof renderActiveAlerts === 'function') renderActiveAlerts();

        initializeClippingEditor();
        bindClippingActions();
        refreshLearningStatus();
    } catch (error) {
        console.error('Clippings tab load failed:', error);
        innerContainer.innerHTML = '<div class="error-state">클리핑 탭을 불러오지 못했습니다.</div>';
    }
}

function initializeClippingEditor() {
    const editorContainer = document.getElementById('editor');
    if (!editorContainer || !window.toastui?.Editor) return;

    const savedText = normalizeMarkdownUrls(localStorage.getItem(CLIPPED_TEXT_KEY) || DEFAULT_CLIPPED_TEXT);
    const isDark = document.body.classList.contains('dark-mode');
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
                const normalizedText = persistClippedText(window.clippingEditor.getMarkdown());
                if (normalizedText !== window.clippingEditor.getMarkdown()) {
                    window.clippingEditor.setMarkdown(normalizedText);
                }
            }
        }
    });

    persistClippedText(savedText);
}

function bindClippingActions() {
    const copyBtn = document.getElementById('copyTextBtn');
    if (copyBtn) {
        copyBtn.addEventListener('click', copyClippingText);
    }

    const clearBtn = document.getElementById('clearTextBtn');
    if (clearBtn) {
        clearBtn.addEventListener('click', () => {
            setEditorText(DEFAULT_CLIPPED_TEXT);
            showToast('클리핑 텍스트를 초기화했습니다.');
        });
    }

    const finalizeLearningBtn = document.getElementById('finalizeLearningBtn');
    if (finalizeLearningBtn) {
        finalizeLearningBtn.addEventListener('click', finalizeCurrentClipping);
    }

    const toggleHistoryBtn = document.getElementById('toggleHistoryBtn');
    const historyContainer = document.getElementById('historyContainer');
    if (toggleHistoryBtn && historyContainer) {
        toggleHistoryBtn.addEventListener('click', () => {
            const isHidden = historyContainer.classList.toggle('hidden');
            if (!isHidden) refreshFinalizationHistory();
        });
    }

    const historyList = document.getElementById('historyList');
    if (historyList) {
        historyList.addEventListener('click', async event => {
            const delBtn = event.target.closest('.btn-history-del');
            if (!delBtn) return;

            const snapshotId = delBtn.dataset.snapshotId;
            if (confirm('이 학습 이력을 삭제할까요? 삭제한 기사는 다시 후보에 포함될 수 있습니다.')) {
                await deleteFinalization(snapshotId);
            }
        });
    }

    const clearAllAlertsBtn = document.getElementById('clearAllAlertsBtn');
    if (clearAllAlertsBtn && typeof window.clearAllAlerts === 'function') {
        clearAllAlertsBtn.addEventListener('click', window.clearAllAlerts);
    }

    const refreshLearningStatusBtn = document.getElementById('refreshLearningStatusBtn');
    if (refreshLearningStatusBtn) {
        refreshLearningStatusBtn.addEventListener('click', refreshLearningStatus);
    }

    const restoreLearningBtn = document.getElementById('restoreLearningBtn');
    if (restoreLearningBtn) {
        restoreLearningBtn.addEventListener('click', restoreLearningFromBackup);
    }
}

async function copyClippingText() {
    const textToCopy = getCurrentClippingText();
    if (!textToCopy) return;

    if (navigator.clipboard && window.isSecureContext) {
        try {
            await navigator.clipboard.writeText(textToCopy);
            showToast('클리핑 텍스트를 복사했습니다.');
        } catch (error) {
            console.error('Copy failed:', error);
            showToast('복사에 실패했습니다.');
        }
        return;
    }

    const temp = document.createElement('textarea');
    temp.value = textToCopy;
    document.body.appendChild(temp);
    temp.select();
    try {
        document.execCommand('copy');
        showToast('클리핑 텍스트를 복사했습니다.');
    } catch (error) {
        console.error('Copy fallback failed:', error);
        alert('복사에 실패했습니다.');
    }
    document.body.removeChild(temp);
}

async function finalizeCurrentClipping() {
    const finalizeLearningBtn = document.getElementById('finalizeLearningBtn');
    const content = getCurrentClippingText();
    if (!content.trim()) {
        showToast('학습할 최종본 내용이 없습니다.');
        return;
    }

    finalizeLearningBtn.disabled = true;
    try {
        const resp = await fetch('/api/clipping-finalizations', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ content })
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || 'finalization failed');

        if (data.duplicate) {
            showToast('이미 학습된 최종본입니다.');
        } else {
            const matched = data.matched_count ?? 0;
            const unmatched = data.unmatched_count ?? 0;
            const backupText = data.auto_backup ? ' GitHub 백업 완료' : '';
            showToast(`최종본 ${data.entry_count}건 저장 완료 (기사 매칭 ${matched}건, 직접 입력 ${unmatched}건)${backupText}`);
            if (data.backup_warning) {
                showToast(`자동 백업 실패: ${data.backup_warning}`);
            }
        }

        await refreshFinalizationHistory();
        await refreshLearningStatus();
    } catch (error) {
        console.error('Final clipping learning failed:', error);
        showToast('최종본 학습 저장에 실패했습니다.');
    } finally {
        finalizeLearningBtn.disabled = false;
    }
}

async function refreshLearningStatus() {
    const badge = document.getElementById('learningStatusBadge');
    const summary = document.getElementById('learningStatusSummary');
    const snapshotCount = document.getElementById('learningSnapshotCount');
    const articleCount = document.getElementById('learningArticleCount');
    const latestAt = document.getElementById('learningLatestAt');
    const backupStatus = document.getElementById('learningBackupStatus');
    const restoreBtn = document.getElementById('restoreLearningBtn');
    const insightList = document.getElementById('learningInsightList');

    if (!badge || !summary) return;

    badge.className = 'learning-status-badge';
    badge.textContent = '확인 중';
    summary.textContent = '학습 데이터와 GitHub 백업 상태를 확인하는 중입니다.';

    try {
        const resp = await fetch('/api/storage/learning-status');
        if (resp.status === 401) {
            summary.innerHTML = '인증이 만료되었습니다. <a href="/login">다시 로그인</a>하세요.';
            badge.textContent = '인증 필요';
            badge.classList.add('warning');
            return;
        }

        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || 'learning status failed');

        const learning = data.learning || {};
        const backup = data.backup || {};
        const backupLearning = data.backup_learning || {};
        const hasLearning = (learning.snapshot_count || 0) > 0 || (learning.finalized_event_count || 0) > 0;

        snapshotCount.textContent = `${learning.snapshot_count || 0}건`;
        articleCount.textContent = `${learning.finalized_event_count || 0}건`;
        latestAt.textContent = formatDateTime(learning.last_finalized_at);

        if (backup.configured) {
            const backupCount = backupLearning.snapshot_count ?? 0;
            backupStatus.textContent = backupLearning.available
                ? `연결됨 · 백업 ${backupCount}건`
                : '연결됨 · 백업 확인 필요';
        } else {
            backupStatus.textContent = '미설정';
        }

        if (hasLearning) {
            badge.textContent = '학습 유지 중';
            badge.classList.add('ready');
            summary.textContent = '현재 서버에 학습 이력이 유지되고 있으며 후보 선별에 반영됩니다.';
        } else if (data.restore_available) {
            badge.textContent = '복원 가능';
            badge.classList.add('warning');
            summary.textContent = '현재 서버 학습 이력은 비어 있지만 GitHub 백업에 학습 데이터가 있습니다.';
        } else {
            badge.textContent = '학습 없음';
            badge.classList.add('warning');
            summary.textContent = '아직 현재 서버에서 확인되는 최종본 학습 이력이 없습니다.';
        }

        if (restoreBtn) {
            restoreBtn.hidden = !data.restore_available;
        }

        if (insightList) {
            const chips = [];
            (learning.top_sources || []).forEach(item => {
                chips.push(`출처 ${escapeHtml(item.source)} ${item.count}회`);
            });
            (learning.top_categories || []).forEach(item => {
                chips.push(`${escapeHtml(item.category)} ${item.count}건`);
            });
            insightList.innerHTML = chips.length
                ? chips.map(label => `<span class="learning-insight-chip">${label}</span>`).join('')
                : '<span class="learning-insight-chip">학습 근거가 쌓이면 이곳에 요약됩니다.</span>';
        }
    } catch (error) {
        console.error('Learning status refresh failed:', error);
        badge.textContent = '확인 실패';
        badge.classList.add('error');
        summary.textContent = '학습 상태를 불러오지 못했습니다. 잠시 후 다시 시도해주세요.';
        if (restoreBtn) restoreBtn.hidden = true;
    }
}

async function restoreLearningFromBackup() {
    if (!confirm('GitHub 백업의 학습 데이터를 현재 서버 저장소로 복원할까요? 현재 서버 저장소가 백업 내용으로 교체됩니다.')) {
        return;
    }

    const restoreBtn = document.getElementById('restoreLearningBtn');
    if (restoreBtn) restoreBtn.disabled = true;

    try {
        const resp = await fetch('/api/storage/restore', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ confirm_replace: true })
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || 'restore failed');

        const learning = data.learning || {};
        showToast(`GitHub 백업을 복원했습니다. 최종본 ${learning.snapshot_count || 0}건이 현재 서버에 반영되었습니다.`);
        await refreshFinalizationHistory();
        await refreshLearningStatus();
    } catch (error) {
        console.error('Learning restore failed:', error);
        showToast(`백업 복원에 실패했습니다: ${error.message}`);
    } finally {
        if (restoreBtn) restoreBtn.disabled = false;
    }
}

async function refreshFinalizationHistory() {
    const list = document.getElementById('historyList');
    if (!list) return;

    try {
        const resp = await fetch('/api/clipping-finalizations');
        if (resp.status === 401) {
            list.innerHTML = '<p class="history-empty">인증이 만료되었습니다. <a href="/login">다시 로그인</a>하세요.</p>';
            return;
        }

        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || 'history load failed');

        if (!data.items || data.items.length === 0) {
            list.innerHTML = '<p class="history-empty">아직 학습된 최종본 이력이 없습니다.</p>';
            return;
        }

        list.innerHTML = data.items.map(item => {
            const dateStr = formatDateTime(item.created_at);
            const preview = escapeHtml(item.preview || '');
            return `
                <div class="history-item">
                    <div class="history-info">
                        <span class="history-date">${dateStr}</span>
                        <p class="history-preview">${preview}...</p>
                    </div>
                    <span class="history-meta">${item.entry_count || 0}건</span>
                    <button class="btn-history-del" data-snapshot-id="${item.id}" title="학습 이력 삭제">삭제</button>
                </div>
            `;
        }).join('');
    } catch (error) {
        console.error('History refresh failed:', error);
        list.innerHTML = '<p class="history-empty">이력을 불러오지 못했습니다. <button class="btn-small" onclick="refreshFinalizationHistory()">다시 시도</button></p>';
    }
}

async function deleteFinalization(snapshotId) {
    try {
        const resp = await fetch(`/api/clipping-finalizations/${snapshotId}`, { method: 'DELETE' });
        const data = await resp.json();
        if (!resp.ok || !data.deleted) throw new Error('Delete failed');
        showToast('학습 이력을 삭제했습니다.');
        await refreshFinalizationHistory();
        await refreshLearningStatus();
    } catch (error) {
        console.error('Delete finalization failed:', error);
        showToast('학습 이력 삭제에 실패했습니다.');
    }
}

window.loadClippingsTab = loadClippingsTab;
window.refreshFinalizationHistory = refreshFinalizationHistory;
window.refreshLearningStatus = refreshLearningStatus;
