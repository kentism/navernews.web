(function () {
    'use strict';
    try {
        document.body.classList.toggle('dark-mode', localStorage.getItem('theme') === 'dark');
    } catch (_) {
        // Theme storage is optional; the password form works without JavaScript.
    }
}());
