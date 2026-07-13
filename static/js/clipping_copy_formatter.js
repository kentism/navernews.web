(function (root, factory) {
    const formatter = factory();

    if (typeof module === 'object' && module.exports) {
        module.exports = formatter;
    }
    if (root) {
        root.ClippingCopyFormatter = formatter;
    }
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
    'use strict';

    /**
     * Converts editor Markdown into the plain-text format used for clipboard output.
     * Stored editor content is not changed.
     */
    function formatClippingText(text, options = {}) {
        const includeUrls = options.includeUrls !== false;
        const lines = String(text || '').split(/\r?\n/);

        return lines
            .map(line => formatLine(line, includeUrls))
            .filter(line => line !== null)
            .join('\n')
            .replace(/\n{3,}/g, '\n\n')
            .trim();
    }

    function formatLine(line, includeUrls) {
        const standaloneUrl = extractStandaloneUrl(line);
        if (standaloneUrl) {
            return includeUrls ? standaloneUrl : null;
        }

        return stripMarkdownPresentation(line);
    }

    function extractStandaloneUrl(line) {
        const trimmed = String(line || '').trim();
        const directUrl = normalizeUrlText(trimmed);
        if (isUrlOnlyText(directUrl)) return directUrl;

        const markdownLink = trimmed.match(/^\[([^\]]*)\]\((.*)\)$/);
        if (!markdownLink) return '';

        const destination = normalizeUrlText(markdownLink[2]);
        return isUrlOnlyText(destination) ? destination : '';
    }

    function stripMarkdownPresentation(line) {
        return String(line || '')
            .replace(/<(https?:\/\/[^>\s]+)>/gi, '$1')
            .replace(/^(#{1,6})\s+/, '')
            .replace(/(\*\*|__)(.+?)\1/g, '$2')
            .replace(/~~(.+?)~~/g, '$1')
            .replace(/(^|[\s(])(\*|_)([^*_]+)\2(?=$|[\s).,!?:;])/g, '$1$3')
            .replace(/\\([\\`*_[\]{}()#+\-.!>])/g, '$1');
    }

    function normalizeUrlText(text) {
        return String(text || '').trim().replace(/^<|>$/g, '');
    }

    function isUrlOnlyText(text) {
        return /^https?:\/\/\S+$/i.test(String(text || '').trim());
    }

    return {
        formatClippingText,
        extractStandaloneUrl
    };
}));
