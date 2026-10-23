(function () {
    'use strict';
    const ui = window.NewsUI;
    const watched = new Set(ui.readArray('watchedKeywords'));
    const clientId = ui.read('navernews_client_id') || `client_${crypto.randomUUID()}`;
    ui.write('navernews_client_id', clientId);
    let stream = null;
    let retryTimer = null;
    let watchdog = null;
    const recent = new Map();

    function syncVisibleWatchCheckboxes() {
        document.querySelectorAll('.watch-checkbox').forEach(box => { box.checked = watched.has(box.dataset.keyword); });
    }
    function renderActiveAlerts() {
        const list = document.getElementById('activeAlertList');
        if (!list) return;
        list.replaceChildren();
        document.getElementById('alertSummaryBadge').textContent = `${watched.size}개 활성`;
        if (!watched.size) {
            const message = document.createElement('p');
            message.className = 'empty-msg'; message.textContent = '활성화된 알림이 없습니다.'; list.append(message);
        }
        for (const keyword of watched) {
            const row = document.createElement('div'); row.className = 'alert-item';
            const label = document.createElement('span'); label.textContent = keyword;
            const button = document.createElement('button'); button.type = 'button';
            button.className = 'btn-remove-alert icon-button'; button.append(ui.icon('x')); button.title = `${keyword} 알림 끄기`;
            button.setAttribute('aria-label', `${keyword} 알림 끄기`);
            button.addEventListener('click', () => changeWatch(keyword, false));
            row.append(label, button); list.append(row);
        }
    }
    function render() {
        ui.write('watchedKeywords', JSON.stringify([...watched]));
        syncVisibleWatchCheckboxes(); renderActiveAlerts();
    }
    async function sync() {
        await ui.request('/api/sync-watch', { method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ client_id: clientId, keywords: [...watched] }) });
    }
    function connect() {
        clearTimeout(retryTimer);
        clearTimeout(watchdog);
        stream?.close();
        if (!watched.size) { stream = null; return; }
        stream = new EventSource(`/api/stream/notifications?client_id=${encodeURIComponent(clientId)}`);
        const resetWatchdog = () => { clearTimeout(watchdog); watchdog = setTimeout(connect, 45000); };
        stream.onopen = resetWatchdog;
        stream.onmessage = event => {
            resetWatchdog();
            if (event.data === 'ping') return;
            if (event.data.startsWith('connected:')) { sync().catch(error => ui.toast(error.message)); return; }
            const keyword = event.data.match(/^\[(.*?)\]/)?.[1];
            if (!keyword || !watched.has(keyword)) return;
            const now = Date.now();
            if (now - (recent.get(keyword) || 0) < 10000) return;
            recent.set(keyword, now);
            ui.toast(event.data);
            if ('Notification' in window && Notification.permission === 'granted') {
                const notification = new Notification('뉴스 클리핑', { body: event.data });
                setTimeout(() => notification.close(), 8000);
            }
            document.querySelectorAll('.tab-pane[data-keyword]').forEach(panel => {
                if (panel.dataset.keyword === keyword && panel.dataset.mode === 'latest') {
                    window.refreshSearchTab(panel.id);
                }
            });
        };
        stream.onerror = () => { clearTimeout(watchdog); stream?.close(); retryTimer = setTimeout(connect, 10000); };
    }
    async function changeWatch(keyword, enabled) {
        const previous = watched.has(keyword);
        if (enabled) watched.add(keyword); else watched.delete(keyword);
        render();
        try {
            await sync();
            connect();
            ui.toast(`[${keyword}] 알림을 ${enabled ? '시작' : '중단'}했습니다.`);
        } catch (error) {
            if (previous) watched.add(keyword); else watched.delete(keyword);
            render(); ui.toast(error.message);
        }
    }
    window.clearAllAlerts = async function () {
        if (!watched.size || !confirm('모든 검색어 알림을 중단할까요?')) return;
        const previous = [...watched];
        watched.clear(); render();
        try { await sync(); connect(); }
        catch (error) { previous.forEach(keyword => watched.add(keyword)); render(); ui.toast(error.message); }
    };
    document.addEventListener('change', event => {
        if (!event.target.matches('.watch-checkbox')) return;
        if (event.target.checked && 'Notification' in window && Notification.permission === 'default') {
            Notification.requestPermission().catch(() => {});
        }
        changeWatch(event.target.dataset.keyword, event.target.checked);
    });
    document.addEventListener('DOMContentLoaded', () => { render(); connect(); });
    window.addEventListener('pagehide', () => { clearTimeout(retryTimer); clearTimeout(watchdog); stream?.close(); });
    window.renderActiveAlerts = renderActiveAlerts;
    window.syncVisibleWatchCheckboxes = syncVisibleWatchCheckboxes;
}());
