(function (root) {
    'use strict';
    const LIMIT = 15;
    const CONCURRENCY = 3;
    function normalizeKeywords(items) {
        return [...new Set(items.filter(item => typeof item === 'string').map(item => item.trim())
            .filter(item => item && item.length <= 300))].slice(0, LIMIT);
    }
    /** Process a batch with bounded concurrency; failure never cancels unrelated searches. */
    async function runBatch(items, worker, onProgress = () => {}) {
        const keywords = normalizeKeywords(items);
        const results = new Array(keywords.length);
        let next = 0;
        let completed = 0;
        function snapshot() {
            const done = results.filter(Boolean);
            return { total: keywords.length, completed, results: [...done],
                loaded: done.filter(item => item.status === 'loaded').length,
                reused: done.filter(item => item.status === 'reused').length,
                cancelled: done.filter(item => item.status === 'cancelled').length,
                failed: done.filter(item => item.status === 'failed').map(item => item.keyword) };
        }
        async function runner() {
            while (next < keywords.length) {
                const index = next++;
                const keyword = keywords[index];
                try {
                    const status = await worker(keyword, index);
                    results[index] = { keyword, status: status || 'loaded' };
                } catch (_) { results[index] = { keyword, status: 'failed' }; }
                completed++;
                onProgress(snapshot());
            }
        }
        onProgress(snapshot());
        await Promise.all(Array.from({ length: Math.min(CONCURRENCY, keywords.length) }, () => runner()));
        return snapshot();
    }
    const api = { LIMIT, CONCURRENCY, normalizeKeywords, runBatch };
    if (typeof module !== 'undefined') module.exports = api;
    else root.NewsSearchBatch = api;
}(typeof window !== 'undefined' ? window : {}));
