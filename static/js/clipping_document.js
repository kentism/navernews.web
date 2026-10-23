(function (root, factory) {
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) root.ClippingDocument = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
    'use strict';
    const categories = ['위원회 관련', '방송·통신 관련', '유관기관 관련', '기타'];
    const emptyText = categories.map(category => `■ ${category}\n\n`).join('');
    function normalizeUrl(value) {
        try {
            const url = new URL(String(value || '').trim());
            if (!['https:', 'http:'].includes(url.protocol)) return '';
            for (const key of [...url.searchParams.keys()]) {
                if (key.toLowerCase().startsWith('utm_')) url.searchParams.delete(key);
            }
            return url.toString();
        } catch (_) { return ''; }
    }
    function buildEntry(item) {
        const date = new Date(item.pubDate || '');
        let suffix = '';
        if (!Number.isNaN(date.getTime())) {
            const parts = new Intl.DateTimeFormat('en-US', {
                timeZone: 'Asia/Seoul', month: '2-digit', day: '2-digit'
            }).formatToParts(date);
            suffix = ` (${parts.find(part => part.type === 'month').value}.${parts.find(part => part.type === 'day').value}.)`;
        }
        const title = String(item.title || '').replace(/[\r\n]+/g, ' ');
        const source = String(item.source || '출처 미상').replace(/[\r\n]+/g, ' ');
        return `▷ ${source} : ${title}${suffix}\n<${normalizeUrl(item.originalLink || item.link)}>`;
    }
    /** Append a batch in one editor update, preserving other sections and article order. */
    function insertArticles(currentText, articles, category) {
        const target = categories.includes(category) ? category : '기타';
        const text = currentText || emptyText;
        const urls = new Set();
        for (const line of text.split('\n')) {
            const value = line.trim();
            const markdown = value.match(/^\[[^\]]*\]\((https?:\/\/.*)\)$/);
            const candidate = markdown ? markdown[1] : value.replace(/^<|>$/g, '');
            if (/^https?:\/\/\S+$/.test(candidate)) urls.add(normalizeUrl(candidate));
        }
        const entries = [];
        for (const item of articles) {
            const url = normalizeUrl(item.originalLink || item.link);
            if (!url || urls.has(url)) continue;
            urls.add(url);
            entries.push(buildEntry(item));
        }
        if (!entries.length) return { text, added: 0 };
        const lines = text.split('\n');
        const isHeader = line => /^\s*(?:\*\*)?■/.test(line);
        const header = lines.findIndex(line => isHeader(line) && line.includes(target));
        if (header === -1) return { text: `${text.trimEnd()}\n\n■ ${target}\n${entries.join('\n\n')}\n`, added: entries.length };
        let end = header + 1;
        while (end < lines.length && !isHeader(lines[end])) end++;
        while (end > header + 1 && !lines[end - 1].trim()) end--;
        lines.splice(end, 0, '', entries.join('\n\n'), '');
        return { text: lines.join('\n'), added: entries.length };
    }
    return { categories, emptyText, normalizeUrl, buildEntry, insertArticles };
}));
