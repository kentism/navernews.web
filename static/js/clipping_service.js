/**
 * clipping_service.js
 *
 * Handles the clipping editor and final clipping learning actions.
 */

const CLIPPED_TEXT_KEY = 'clippedTextContent';
const DEFAULT_CLIPPED_TEXT = '■ 위원회 관련\n\n■ 방송·통신 관련\n\n■ 유관기관 관련\n\n■ 기타\n\n';
const LEARNING_HISTORY_PASSWORD = 'kcsc1377!';
const LEARNING_HISTORY_UNLOCK_KEY = 'learningHistoryUnlocked';

window.clippingEditor = null;
let isSyncingClippingEditor = false;

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

function notifyClippingToast(message) {
    if (typeof window.showToast === 'function') {
        window.showToast(message);
    }
}

function isLearningHistoryUnlocked() {
    return sessionStorage.getItem(LEARNING_HISTORY_UNLOCK_KEY) === 'true';
}

function setLearningHistoryUnlocked(unlocked) {
    if (unlocked) {
        sessionStorage.setItem(LEARNING_HISTORY_UNLOCK_KEY, 'true');
    } else {
        sessionStorage.removeItem(LEARNING_HISTORY_UNLOCK_KEY);
    }
}

function applyLearningHistoryLockState() {
    const lockPanel = document.getElementById('learningHistoryLockPanel');
    const content = document.getElementById('learningHistoryContent');
    if (!lockPanel && !content) return true;

    const unlocked = isLearningHistoryUnlocked();
    if (lockPanel) lockPanel.hidden = unlocked;
    if (content) content.hidden = !unlocked;
    return unlocked;
}

function requireLearningHistoryUnlock(showNotice = true) {
    if (applyLearningHistoryLockState()) return true;

    if (showNotice) {
        const message = document.getElementById('learningHistoryLockMessage');
        if (message) message.textContent = '관리자 비밀번호를 입력하면 학습 이력을 확인할 수 있습니다.';
        notifyClippingToast('학습 이력 기능이 잠겨 있습니다.');
    }
    return false;
}

function bindLearningHistoryLock() {
    const lockPanel = document.getElementById('learningHistoryLockPanel');
    const input = document.getElementById('learningHistoryPassword');
    const message = document.getElementById('learningHistoryLockMessage');
    if (!lockPanel || !input || lockPanel.dataset.bound) return;

    lockPanel.dataset.bound = 'true';
    lockPanel.addEventListener('submit', async event => {
        event.preventDefault();
        if (input.value === LEARNING_HISTORY_PASSWORD) {
            setLearningHistoryUnlocked(true);
            input.value = '';
            if (message) message.textContent = '';
            applyLearningHistoryLockState();
            notifyClippingToast('학습 이력 잠금을 해제했습니다.');
            await refreshLearningStatus();
            await refreshFinalizationHistory();
            return;
        }

        input.value = '';
        input.focus();
        if (message) message.textContent = '비밀번호가 일치하지 않습니다.';
        notifyClippingToast('학습 이력 비밀번호가 일치하지 않습니다.');
    });
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
        setClippingEditorMarkdown(normalized);
    }
    const textArea = document.getElementById('clippingTextArea');
    if (textArea) {
        textArea.value = normalized;
    }
}

function setClippingEditorMarkdown(text) {
    if (!window.clippingEditor) return;

    isSyncingClippingEditor = true;
    try {
        window.clippingEditor.setMarkdown(text);
    } finally {
        setTimeout(() => {
            isSyncingClippingEditor = false;
        }, 0);
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
    notifyClippingToast(`[${targetCategory}] 클리핑에 추가했습니다.`);

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
                if (isSyncingClippingEditor) return;
                const currentText = window.clippingEditor.getMarkdown();
                const normalizedText = persistClippedText(currentText);
                if (normalizedText !== currentText) {
                    setClippingEditorMarkdown(normalizedText);
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
            notifyClippingToast('클리핑 텍스트를 초기화했습니다.');
        });
    }

    const finalizeLearningBtn = document.getElementById('finalizeLearningBtn');
    if (finalizeLearningBtn) {
        finalizeLearningBtn.addEventListener('click', finalizeCurrentClipping);
    }

    const clearAllAlertsBtn = document.getElementById('clearAllAlertsBtn');
    if (clearAllAlertsBtn && typeof window.clearAllAlerts === 'function') {
        clearAllAlertsBtn.addEventListener('click', window.clearAllAlerts);
    }
}

function initializeLearningPanel() {
    bindLearningHistoryLock();
    const unlocked = applyLearningHistoryLockState();

    const historyList = document.getElementById('historyList');
    if (historyList && !historyList.dataset.bound) {
        historyList.dataset.bound = 'true';
        historyList.addEventListener('click', async event => {
            const editBtn = event.target.closest('.btn-history-edit');
            if (editBtn) {
                await loadFinalizationForEdit(editBtn.dataset.snapshotId, editBtn);
                return;
            }

            const delBtn = event.target.closest('.btn-history-del');
            if (!delBtn) return;

            const snapshotId = delBtn.dataset.snapshotId;
            if (confirm('이 학습 이력을 삭제할까요? 삭제한 기사는 다시 후보에 포함될 수 있습니다.')) {
                await deleteFinalization(snapshotId, delBtn);
            }
        });
    }

    const editPanel = document.getElementById('finalizationEditPanel');
    if (editPanel && !editPanel.dataset.bound) {
        editPanel.dataset.bound = 'true';
        editPanel.addEventListener('submit', saveFinalizationEdit);
    }

    const cancelEditBtn = document.getElementById('cancelFinalizationEditBtn');
    if (cancelEditBtn && !cancelEditBtn.dataset.bound) {
        cancelEditBtn.dataset.bound = 'true';
        cancelEditBtn.addEventListener('click', closeFinalizationEditPanel);
    }

    const refreshLearningStatusBtn = document.getElementById('refreshLearningStatusBtn');
    if (refreshLearningStatusBtn && !refreshLearningStatusBtn.dataset.bound) {
        refreshLearningStatusBtn.dataset.bound = 'true';
        refreshLearningStatusBtn.addEventListener('click', refreshLearningStatus);
    }

    const restoreLearningBtn = document.getElementById('restoreLearningBtn');
    if (restoreLearningBtn && !restoreLearningBtn.dataset.bound) {
        restoreLearningBtn.dataset.bound = 'true';
        restoreLearningBtn.addEventListener('click', restoreLearningFromBackup);
    }

    if (!unlocked) return;
    refreshLearningStatus();
    refreshFinalizationHistory();
}

async function copyClippingText() {
    const textToCopy = getCurrentClippingText();
    if (!textToCopy) return;

    if (navigator.clipboard && window.isSecureContext) {
        try {
            await navigator.clipboard.writeText(textToCopy);
            notifyClippingToast('클리핑 텍스트를 복사했습니다.');
        } catch (error) {
            console.error('Copy failed:', error);
            notifyClippingToast('복사에 실패했습니다.');
        }
        return;
    }

    const temp = document.createElement('textarea');
    temp.value = textToCopy;
    document.body.appendChild(temp);
    temp.select();
    try {
        document.execCommand('copy');
        notifyClippingToast('클리핑 텍스트를 복사했습니다.');
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
        notifyClippingToast('학습할 최종본 내용이 없습니다.');
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
            notifyClippingToast('이미 학습된 최종본입니다.');
        } else {
            const matched = data.matched_count ?? 0;
            const unmatched = data.unmatched_count ?? 0;
            const backupText = data.auto_backup ? ' GitHub 백업 완료' : '';
            notifyClippingToast(`최종본 ${data.entry_count}건 저장 완료 (기사 매칭 ${matched}건, 직접 입력 ${unmatched}건)${backupText}`);
            if (data.backup_warning) {
                notifyClippingToast(`자동 백업 실패: ${data.backup_warning}`);
            }
        }

        await refreshFinalizationHistory();
        await refreshLearningStatus();
    } catch (error) {
        console.error('Final clipping learning failed:', error);
        notifyClippingToast('최종본 학습 저장에 실패했습니다.');
    } finally {
        finalizeLearningBtn.disabled = false;
    }
}

async function refreshLearningStatus() {
    if (!requireLearningHistoryUnlock(false)) return;

    const badge = document.getElementById('learningStatusBadge');
    const summary = document.getElementById('learningStatusSummary');
    const snapshotCount = document.getElementById('learningSnapshotCount');
    const articleCount = document.getElementById('learningArticleCount');
    const latestAt = document.getElementById('learningLatestAt');
    const backupStatus = document.getElementById('learningBackupStatus');
    const restoreBtn = document.getElementById('restoreLearningBtn');
    const restoreNotice = document.getElementById('learningRestoreNotice');
    const insightList = document.getElementById('learningInsightList');
    const historyMeta = document.getElementById('learningHistoryMeta');

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

        snapshotCount.textContent = `최종본 ${learning.snapshot_count || 0}건`;
        articleCount.textContent = `학습 기사 ${learning.finalized_event_count || 0}건`;
        latestAt.textContent = `마지막 학습 ${formatDateTime(learning.last_finalized_at)}`;

        if (backup.configured) {
            const backupCount = backupLearning.snapshot_count ?? 0;
            backupStatus.textContent = backupLearning.available
                ? `백업 ${backupCount}건`
                : '백업 확인 필요';
        } else {
            backupStatus.textContent = '백업 미설정';
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
        if (restoreNotice) {
            restoreNotice.hidden = !data.restore_available;
        }
        if (historyMeta) {
            historyMeta.textContent = hasLearning
                ? `총 ${learning.snapshot_count || 0}개 최종본, ${learning.finalized_event_count || 0}개 기사 학습`
                : '아직 표시할 학습 이력이 없습니다';
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
        if (restoreNotice) restoreNotice.hidden = true;
    }
}

async function restoreLearningFromBackup() {
    if (!requireLearningHistoryUnlock()) return;

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
        notifyClippingToast(`GitHub 백업을 복원했습니다. 최종본 ${learning.snapshot_count || 0}건이 현재 서버에 반영되었습니다.`);
        await refreshFinalizationHistory();
        await refreshLearningStatus();
    } catch (error) {
        console.error('Learning restore failed:', error);
        notifyClippingToast(`백업 복원에 실패했습니다: ${error.message}`);
    } finally {
        if (restoreBtn) restoreBtn.disabled = false;
    }
}

async function refreshFinalizationHistory() {
    if (!requireLearningHistoryUnlock(false)) return;

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
            const historyMeta = document.getElementById('learningHistoryMeta');
            if (historyMeta) historyMeta.textContent = '아직 표시할 학습 이력이 없습니다';
            return;
        }

        const historyMeta = document.getElementById('learningHistoryMeta');
        if (historyMeta) historyMeta.textContent = `최근 ${data.items.length}건 표시 중`;

        list.innerHTML = data.items.map(item => {
            const dateStr = formatDateTime(item.created_at);
            const preview = escapeHtml(item.preview || '');
            return `
                <div class="history-item" data-history-snapshot-id="${item.id}">
                    <div class="history-info">
                        <span class="history-date">${dateStr}</span>
                        <p class="history-preview">${preview}...</p>
                    </div>
                    <span class="history-meta">${item.entry_count || 0}건</span>
                    <button class="btn-history-edit" data-snapshot-id="${item.id}" title="학습 이력 수정">수정</button>
                    <button class="btn-history-del" data-snapshot-id="${item.id}" title="학습 이력 삭제">삭제</button>
                </div>
            `;
        }).join('');
    } catch (error) {
        console.error('History refresh failed:', error);
        list.innerHTML = '<p class="history-empty">이력을 불러오지 못했습니다. <button class="btn-small" onclick="refreshFinalizationHistory()">다시 시도</button></p>';
    }
}

function closeFinalizationEditPanel() {
    const panel = document.getElementById('finalizationEditPanel');
    const textarea = document.getElementById('finalizationEditContent');
    const status = document.getElementById('finalizationEditStatus');
    const title = document.getElementById('finalizationEditTitle');
    if (panel) {
        panel.hidden = true;
        delete panel.dataset.snapshotId;
    }
    if (textarea) textarea.value = '';
    if (title) title.textContent = '최종본 수정';
    if (status) status.textContent = '수정 후 저장하면 학습 이력과 GitHub 백업이 함께 갱신됩니다.';
}

async function loadFinalizationForEdit(snapshotId, button = null) {
    if (!requireLearningHistoryUnlock()) return;

    const panel = document.getElementById('finalizationEditPanel');
    const textarea = document.getElementById('finalizationEditContent');
    const status = document.getElementById('finalizationEditStatus');
    const title = document.getElementById('finalizationEditTitle');
    if (!panel || !textarea) return;

    const originalButtonText = button ? button.textContent : '';
    if (button) {
        button.disabled = true;
        button.textContent = '불러오는 중';
    }
    if (status) status.textContent = '최종본 내용을 불러오는 중입니다.';

    try {
        const resp = await fetch(`/api/clipping-finalizations/${snapshotId}`);
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || '최종본 조회 실패');

        const item = data.item || {};
        panel.hidden = false;
        panel.dataset.snapshotId = snapshotId;
        textarea.value = item.content || '';
        if (title) title.textContent = `최종본 수정 #${snapshotId}`;
        if (status) status.textContent = '내용을 수정한 뒤 저장하면 학습 이벤트와 GitHub 백업이 갱신됩니다.';
        textarea.focus();
    } catch (error) {
        console.error('Finalization edit load failed:', error);
        if (status) status.textContent = '최종본 내용을 불러오지 못했습니다.';
        notifyClippingToast('최종본 내용을 불러오지 못했습니다.');
    } finally {
        if (button) {
            button.disabled = false;
            button.textContent = originalButtonText || '수정';
        }
    }
}

async function saveFinalizationEdit(event) {
    event.preventDefault();
    if (!requireLearningHistoryUnlock()) return;

    const panel = document.getElementById('finalizationEditPanel');
    const textarea = document.getElementById('finalizationEditContent');
    const status = document.getElementById('finalizationEditStatus');
    const saveBtn = document.getElementById('saveFinalizationEditBtn');
    const snapshotId = panel ? panel.dataset.snapshotId : '';
    const content = textarea ? textarea.value : '';

    if (!snapshotId || !content.trim()) {
        notifyClippingToast('수정할 최종본 내용이 없습니다.');
        return;
    }

    if (saveBtn) {
        saveBtn.disabled = true;
        saveBtn.textContent = '저장 중';
    }
    if (status) status.textContent = '수정 내용을 저장하고 GitHub 백업에 반영하는 중입니다.';

    try {
        const resp = await fetch(`/api/clipping-finalizations/${snapshotId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ content })
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || '최종본 수정 실패');

        const matched = data.matched_count ?? 0;
        const unmatched = data.unmatched_count ?? 0;
        const backupText = data.auto_backup ? ' GitHub 백업 완료' : '';
        notifyClippingToast(`최종본 수정 완료 (기사 매칭 ${matched}건, 직접 입력 ${unmatched}건)${backupText}`);
        if (data.backup_warning) {
            notifyClippingToast(`자동 백업 실패: ${data.backup_warning}`);
        }
        closeFinalizationEditPanel();
        await refreshFinalizationHistory();
        await refreshLearningStatus();
    } catch (error) {
        console.error('Finalization edit save failed:', error);
        if (status) status.textContent = error.message || '최종본 수정에 실패했습니다.';
        notifyClippingToast(error.message || '최종본 수정에 실패했습니다.');
    } finally {
        if (saveBtn) {
            saveBtn.disabled = false;
            saveBtn.textContent = '수정 저장';
        }
    }
}

async function deleteFinalization(snapshotId, button = null) {
    if (!requireLearningHistoryUnlock()) return;

    const row = button ? button.closest('.history-item') : null;
    const originalButtonText = button ? button.textContent : '';
    const historyMeta = document.getElementById('learningHistoryMeta');

    if (button) {
        button.disabled = true;
        button.textContent = '삭제 중';
    }
    if (row) row.classList.add('is-removing');
    if (historyMeta) historyMeta.textContent = '학습 이력 삭제를 반영하는 중입니다.';

    try {
        const resp = await fetch(`/api/clipping-finalizations/${snapshotId}`, { method: 'DELETE' });
        const data = await resp.json();
        if (!resp.ok || !data.deleted) throw new Error('Delete failed');

        if (row) {
            row.remove();
            const list = document.getElementById('historyList');
            if (list && !list.querySelector('.history-item')) {
                list.innerHTML = '<p class="history-empty">아직 학습된 최종본 이력이 없습니다.</p>';
            }
        }

        const backupText = data.auto_backup ? ' GitHub 백업 완료' : '';
        notifyClippingToast(`학습 이력을 삭제했습니다.${backupText}`);
        if (data.backup_warning) {
            notifyClippingToast(`자동 백업 실패: ${data.backup_warning}`);
        }
        await refreshFinalizationHistory();
        await refreshLearningStatus();
    } catch (error) {
        console.error('Delete finalization failed:', error);
        if (button) {
            button.disabled = false;
            button.textContent = originalButtonText || '삭제';
        }
        if (row) row.classList.remove('is-removing');
        notifyClippingToast('학습 이력 삭제에 실패했습니다.');
    }
}

window.loadClippingsTab = loadClippingsTab;
window.initializeLearningPanel = initializeLearningPanel;
window.refreshFinalizationHistory = refreshFinalizationHistory;
window.refreshLearningStatus = refreshLearningStatus;
