(function () {
    'use strict';
    const labels = { queued: '대기', loading: '검색 중', ready: '', failed: '실패' };

    function update() {
        const button = document.getElementById('searchTabsMenuBtn');
        const list = document.getElementById('searchTabsMenuList');
        if (!button || !list) return;
        const panels = [...document.querySelectorAll('.tab-pane[data-keyword]')];
        document.getElementById('searchTabsCount').textContent = panels.length;
        button.disabled = !panels.length;
        const query = document.getElementById('searchTabsFilter').value.trim().toLocaleLowerCase();
        list.replaceChildren();
        for (const panel of panels.filter(item => item.dataset.keyword.toLocaleLowerCase().includes(query))) {
            const row = document.createElement('li');
            const target = document.createElement('button'); target.type = 'button';
            const label = document.createElement('span'); label.textContent = panel.dataset.keyword;
            const status = document.createElement('small'); status.textContent = labels[panel.dataset.searchState] || '';
            status.className = panel.dataset.searchState === 'failed' ? 'save-failed' : '';
            if (panel.classList.contains('active')) target.setAttribute('aria-current', 'page');
            target.append(label, status);
            target.addEventListener('click', () => { window.switchTab(panel.id); closeMenu(); button.focus(); });
            row.append(target); list.append(row);
        }
        if (!list.children.length) {
            const empty = document.createElement('li'); empty.className = 'empty-msg';
            empty.textContent = panels.length ? '일치하는 검색 탭이 없습니다.' : '열린 검색 탭이 없습니다.';
            list.append(empty);
        }
        if (!panels.length) closeMenu();
    }
    function closeMenu() {
        document.getElementById('searchTabsMenu').hidden = true;
        document.getElementById('searchTabsMenuBtn').setAttribute('aria-expanded', 'false');
    }
    document.addEventListener('DOMContentLoaded', () => {
        const button = document.getElementById('searchTabsMenuBtn');
        const menu = document.getElementById('searchTabsMenu');
        const filter = document.getElementById('searchTabsFilter');
        button.addEventListener('click', () => {
            const opening = menu.hidden;
            menu.hidden = !opening;
            button.setAttribute('aria-expanded', String(opening));
            if (opening) { filter.value = ''; update(); filter.focus(); }
        });
        filter.addEventListener('input', update);
        document.addEventListener('click', event => { if (!event.target.closest('.search-tabs-picker')) closeMenu(); });
        document.addEventListener('keydown', event => {
            if (event.key === 'Escape' && !menu.hidden) { closeMenu(); button.focus(); }
        });
        update();
    });
    window.NewsSearchTabs = { update };
}());
