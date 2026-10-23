(function (root) {
    'use strict';
    function indicatorBounds(button, viewport, wrapper) {
        const left = Math.max(button.left + 12, viewport.left);
        const right = Math.min(button.right - 12, viewport.right);
        return right > left ? { x: left - wrapper.left, width: right - left } : null;
    }

    /** Motion is cancellable presentation only; it never delays requests or replaces editor nodes. */
    function createMotion(env) {
        const media = env.matchMedia('(prefers-reduced-motion: reduce)');
        const animations = new Map();
        const loadingTimers = new WeakMap();
        const busyIcons = new WeakMap();
        const feedback = new WeakMap();
        let indicatorFrame = null;
        function visible(element) {
            const pane = element?.closest?.('.tab-pane');
            return element?.isConnected && env.document.visibilityState !== 'hidden' && (!pane || pane.classList.contains('active'));
        }
        function stop(element) {
            const animation = animations.get(element);
            animations.delete(element);
            animation?.cancel();
        }
        function currentTransform(element) {
            return animations.has(element) ? env.getComputedStyle(element).transform : element.style.transform;
        }
        function play(element, frames, duration) {
            stop(element);
            if (media.matches || !visible(element) || !element.animate) return;
            const animation = element.animate(frames, { duration, easing: 'cubic-bezier(.2,.7,.3,1)' });
            animations.set(element, animation);
            const cleanup = () => { if (animations.get(element) === animation) animations.delete(element); };
            animation.finished.then(cleanup, cleanup);
        }
        function reveal(element, kind = 'panel') {
            const menu = kind === 'menu';
            play(element, [{ opacity: menu ? 0 : .65, transform: `translateY(${menu ? 3 : 2}px)` },
                { opacity: 1, transform: 'translateY(0)' }], menu ? 120 : kind === 'results' ? 180 : 150);
        }
        function endLoading(panel) {
            env.clearTimeout(loadingTimers.get(panel)); loadingTimers.delete(panel);
            const skeleton = panel.querySelector('.search-loading')?.querySelector('.search-skeleton');
            if (skeleton) skeleton.hidden = true;
        }
        function syncLoading(panel) {
            const shell = panel.querySelector('.search-loading');
            if (!shell) return;
            env.clearTimeout(loadingTimers.get(panel)); loadingTimers.delete(panel);
            const loading = panel.dataset.searchState === 'loading';
            shell.querySelector('[data-loading-label]').textContent = loading ? '검색 중' : '검색 대기 중';
            shell.querySelector('use').setAttribute('href', `/static/icons.svg?v=motion-1#${loading ? 'loader-circle' : 'clock-3'}`);
            const skeleton = shell.querySelector('.search-skeleton');
            if (!visible(panel) || !['queued', 'loading'].includes(panel.dataset.searchState)) { skeleton.hidden = true; return; }
            if (!skeleton.hidden) return;
            loadingTimers.set(panel, env.setTimeout(() => {
                loadingTimers.delete(panel);
                if (visible(panel) && ['queued', 'loading'].includes(panel.dataset.searchState)) skeleton.hidden = false;
            }, 150));
        }
        function mountLoading(panel) {
            const content = panel.querySelector('.search-panel-content');
            if (content.querySelector('.search-results-list, .search-loading')) return;
            const shell = env.document.createElement('section'); shell.className = 'search-loading';
            shell.innerHTML = '<div class="loading-heading"><h2></h2><div class="loading-state" role="status" aria-live="polite"><svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><use href="/static/icons.svg?v=motion-1#clock-3"></use></svg><span data-loading-label>검색 대기 중</span></div></div><div class="search-skeleton" aria-hidden="true" hidden></div>';
            shell.querySelector('h2').textContent = panel.dataset.keyword;
            const skeleton = shell.querySelector('.search-skeleton');
            for (let i = 0; i < 3; i++) {
                const card = env.document.createElement('div'); card.className = 'skeleton-news-card';
                card.innerHTML = '<div class="skeleton-bars"><span class="skeleton-source"></span><span class="skeleton-title"></span><span></span><span class="skeleton-short"></span><span class="skeleton-action"></span></div>';
                skeleton.append(card);
            }
            content.replaceChildren(shell);
        }
        function deactivate(panel) {
            endLoading(panel);
            for (const element of animations.keys()) if (element === panel || panel.contains(element)) stop(element);
        }
        function revealResults(panel, cards) {
            if (!visible(panel)) return;
            if (!cards) {
                const items = panel.querySelector('.news-items');
                reveal(items?.children.length ? items : panel.querySelector('.empty-state'), 'results'); return;
            }
            cards.filter(card => { const box = card.getBoundingClientRect(); return box.bottom > 0 && box.top < env.innerHeight; })
                .slice(0, 8).forEach(card => reveal(card, 'results'));
        }
        function setBusy(button, busy) {
            if (!button) return;
            const use = button.querySelector('.icon use');
            if (busy) {
                button.setAttribute('aria-busy', 'true');
                if (use && !busyIcons.has(button)) { busyIcons.set(button, use.getAttribute('href')); use.setAttribute('href', '/static/icons.svg?v=motion-1#loader-circle'); }
            } else {
                button.removeAttribute('aria-busy');
                if (use && busyIcons.has(button)) use.setAttribute('href', busyIcons.get(button));
                busyIcons.delete(button);
            }
        }
        function success(button) {
            const use = button?.querySelector('.icon use');
            if (!use) return;
            const previous = feedback.get(button);
            env.clearTimeout(previous?.timer);
            const original = previous?.original || use.getAttribute('href');
            use.setAttribute('href', '/static/icons.svg?v=motion-1#check'); button.classList.add('feedback-success');
            const timer = env.setTimeout(() => {
                use.setAttribute('href', original); button.classList.remove('feedback-success'); feedback.delete(button);
            }, 800);
            feedback.set(button, { original, timer });
        }
        function updateIndicator(animate = true) {
            if (indicatorFrame !== null) { env.cancelAnimationFrame(indicatorFrame); indicatorFrame = null; }
            const wrapper = env.document.querySelector('.tabs-nav-wrapper');
            const indicator = env.document.getElementById('activeTabIndicator');
            const button = wrapper?.querySelector('.tab-btn.active');
            if (!indicator || !button) return;
            const viewport = button.closest('.tabs-nav, .fixed-tabs-nav');
            const bounds = indicatorBounds(button.getBoundingClientRect(), viewport.getBoundingClientRect(), wrapper.getBoundingClientRect());
            wrapper.classList.add('has-motion-indicator');
            indicator.hidden = !bounds;
            if (!bounds) { stop(indicator); return; }
            const before = currentTransform(indicator);
            const after = `translateX(${bounds.x}px) scaleX(${bounds.width})`;
            indicator.style.transform = after;
            if (animate && before && before !== after) play(indicator, [{ transform: before }, { transform: after }], 150);
            else stop(indicator);
        }
        function scheduleIndicator() {
            if (indicatorFrame !== null) return;
            indicatorFrame = env.requestAnimationFrame(() => { indicatorFrame = null; updateIndicator(false); });
        }
        function scrollTab(button) {
            const nav = button?.closest('.tabs-nav');
            if (!nav) return;
            const box = button.getBoundingClientRect(); const viewport = nav.getBoundingClientRect();
            const delta = box.left < viewport.left ? box.left - viewport.left : box.right > viewport.right ? box.right - viewport.right : 0;
            if (delta) nav.scrollBy({ left: delta, behavior: media.matches ? 'auto' : 'smooth' });
        }
        function progress(fill, ratio) {
            const before = currentTransform(fill) || 'scaleX(0)';
            const after = `scaleX(${Math.max(0, Math.min(1, ratio))})`;
            fill.style.transform = after;
            if (ratio > 0 && before !== after) play(fill, [{ transform: before }, { transform: after }], 180);
            else stop(fill);
        }
        media.addEventListener?.('change', () => { for (const element of animations.keys()) stop(element); scheduleIndicator(); });
        return { reveal, stop, deactivate, mountLoading, syncLoading, endLoading, revealResults, setBusy, success,
            updateIndicator, scheduleIndicator, scrollTab, progress, scrollBehavior: () => media.matches ? 'auto' : 'smooth' };
    }
    if (typeof module !== 'undefined') module.exports = { createMotion, indicatorBounds };
    else {
        root.NewsMotion = createMotion(root);
        root.document.addEventListener('DOMContentLoaded', () => {
            const motion = root.NewsMotion;
            motion.updateIndicator(false);
            root.document.querySelector('.tabs-nav').addEventListener('scroll', motion.scheduleIndicator, { passive: true });
            root.addEventListener('resize', () => {
                motion.scrollTab(root.document.querySelector('.tab-btn.active')); motion.scheduleIndicator();
            }, { passive: true });
            if (root.ResizeObserver) {
                const observer = new root.ResizeObserver(motion.scheduleIndicator);
                root.document.querySelectorAll('.tabs-nav-wrapper, .fixed-tabs-nav, .tabs-nav').forEach(element => observer.observe(element));
            }
            root.document.addEventListener('visibilitychange', () => {
                root.document.querySelectorAll('.tab-pane').forEach(panel => {
                    if (root.document.hidden || !panel.classList.contains('active')) motion.deactivate(panel);
                    else motion.syncLoading(panel);
                });
            });
        });
    }
}(typeof window !== 'undefined' ? window : {}));
