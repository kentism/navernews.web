(function () {
    'use strict';
    function read(key, fallback = '') {
        try { return localStorage.getItem(key) ?? fallback; } catch (_) { return fallback; }
    }
    function write(key, value) {
        try { localStorage.setItem(key, value); return true; } catch (_) { return false; }
    }
    function readArray(key) {
        try {
            const value = JSON.parse(read(key, '[]'));
            return Array.isArray(value) ? value.filter(item => typeof item === 'string') : [];
        } catch (_) { return []; }
    }
    function toast(message) {
        const container = document.getElementById('toastContainer');
        if (!container) return;
        const item = document.createElement('div');
        item.className = 'toast';
        item.textContent = message;
        container.append(item);
        while (container.children.length > 2) container.firstElementChild.remove();
        requestAnimationFrame(() => item.classList.add('show'));
        setTimeout(() => { item.classList.remove('show'); setTimeout(() => item.remove(), 300); }, 4500);
    }
    async function request(url, options) {
        const response = await fetch(url, options);
        if (response.status === 401 || response.redirected) {
            throw new Error('인증이 만료되었습니다. 다시 로그인해주세요.');
        }
        if (!response.ok) {
            const data = await response.json().catch(() => ({}));
            throw new Error(typeof data.error === 'string' ? data.error : '요청에 실패했습니다. 다시 시도해주세요.');
        }
        return response;
    }
    function download(text, filename, type = 'text/plain;charset=utf-8') {
        const url = URL.createObjectURL(new Blob(['\uFEFF', text], { type }));
        const link = document.createElement('a');
        link.href = url;
        link.download = filename;
        document.body.append(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
    }
    function icon(name) {
        const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        svg.classList.add('icon'); svg.setAttribute('viewBox', '0 0 24 24');
        svg.setAttribute('aria-hidden', 'true'); svg.setAttribute('focusable', 'false');
        const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
        use.setAttribute('href', `/static/icons.svg?v=motion-1#${name}`); svg.append(use);
        return svg;
    }
    window.NewsUI = { read, write, readArray, toast, request, download, icon };
    window.showToast = toast;
}());
