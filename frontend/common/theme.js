/**
 * Theme Toggle System
 */

(function() {
    const THEME_KEY = 'upbit-theme';
    const DARK = 'dark';
    const LIGHT = 'light';

    // Get saved theme or default to dark
    function getSavedTheme() {
        return localStorage.getItem(THEME_KEY) || DARK;
    }

    // Save theme preference
    function saveTheme(theme) {
        localStorage.setItem(THEME_KEY, theme);
    }

    // Apply theme to document
    function applyTheme(theme, animate = false) {
        if (animate) {
            document.body.classList.add('theme-transitioning');
        }

        document.documentElement.setAttribute('data-theme', theme);

        if (animate) {
            setTimeout(() => {
                document.body.classList.remove('theme-transitioning');
            }, 300);
        }

        // Update toggle button icon
        updateToggleButtons(theme);

        // Dispatch custom event for components that need to react
        window.dispatchEvent(new CustomEvent('themechange', { detail: { theme } }));
    }

    // Update all toggle button icons
    function updateToggleButtons(theme) {
        document.querySelectorAll('.theme-toggle').forEach(btn => {
            const icon = btn.querySelector('.theme-toggle-icon');
            const text = btn.querySelector('.theme-toggle-text');
            if (icon) {
                icon.textContent = theme === DARK ? '🌙' : '☀️';
            }
            if (text) {
                text.textContent = theme === DARK ? 'Dark' : 'Light';
            }
        });
    }

    // Toggle between themes
    function toggleTheme() {
        const current = document.documentElement.getAttribute('data-theme') || DARK;
        const next = current === DARK ? LIGHT : DARK;
        applyTheme(next, true);
        saveTheme(next);
    }

    // Initialize theme on page load
    function initTheme() {
        const savedTheme = getSavedTheme();
        applyTheme(savedTheme, false);
    }

    // Create and insert toggle button
    function createToggleButton() {
        const btn = document.createElement('button');
        btn.className = 'theme-toggle';
        btn.setAttribute('aria-label', 'Toggle theme');
        btn.innerHTML = `
            <span class="theme-toggle-icon">🌙</span>
            <span class="theme-toggle-text">Dark</span>
        `;
        btn.addEventListener('click', toggleTheme);
        return btn;
    }

    // Auto-insert toggle button into nav if placeholder exists
    function autoInsertToggle() {
        const placeholder = document.getElementById('theme-toggle-container');
        if (placeholder) {
            placeholder.appendChild(createToggleButton());
        }
    }

    // Apply theme immediately (before DOM ready) to prevent flash
    (function() {
        const savedTheme = getSavedTheme();
        document.documentElement.setAttribute('data-theme', savedTheme);
    })();

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
            initTheme();
            autoInsertToggle();
        });
    } else {
        initTheme();
        autoInsertToggle();
    }

    // Expose API globally
    window.ThemeToggle = {
        toggle: toggleTheme,
        set: (theme) => {
            applyTheme(theme, true);
            saveTheme(theme);
        },
        get: () => document.documentElement.getAttribute('data-theme') || DARK,
        createButton: createToggleButton
    };
})();
