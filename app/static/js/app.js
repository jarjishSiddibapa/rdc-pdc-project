/**
 * RDC PDC Manager — Client-Side JavaScript
 * Phase 7: XSS-safe DOM construction (no innerHTML with user data)
 * Phase 6: IntersectionObserver for counters, debounced inputs
 */

'use strict';

document.addEventListener('DOMContentLoaded', function () {
    initTheme();
    initSidebar();
    initDropdowns();
    initNotifications();
    initFlashMessages();
    initCounters();
    initPasswordToggle();
    initFormEnhancements();
    // ── Stripe-like effects ──
    initMouseSpotlight();
    initScrollReveal();
    initButtonRipple();
});

/* ─── THEME ──────────────────────────────────────────────────── */
// NOTE: The initial theme attribute is set inline in <head> to prevent FOUC.
// This function only wires the toggle button.
function initTheme() {
    const btn = document.getElementById('themeToggle');
    if (!btn) return;

    // Sync aria-label with current theme on load
    function syncLabel() {
        const current = document.documentElement.getAttribute('data-theme') || 'dark';
        btn.setAttribute('aria-label', current === 'dark' ? 'Switch to light mode' : 'Switch to dark mode');
    }
    syncLabel();

    btn.addEventListener('click', () => {
        const current = document.documentElement.getAttribute('data-theme');
        const next = current === 'dark' ? 'light' : 'dark';
        document.documentElement.setAttribute('data-theme', next);
        localStorage.setItem('rdc-theme', next);
        syncLabel();
    });
}

/* ─── SIDEBAR ────────────────────────────────────────────────── */
function initSidebar() {
    const toggle       = document.getElementById('sidebarToggle');
    const mobileToggle = document.getElementById('mobileToggle');
    const sidebar      = document.getElementById('sidebar');
    const overlay      = document.getElementById('sidebarOverlay');
    const mainWrapper  = document.getElementById('mainWrapper');

    function openMobileSidebar() {
        sidebar.classList.add('open');
        if (overlay) overlay.classList.add('active');
        if (mobileToggle) mobileToggle.setAttribute('aria-expanded', 'true');
    }

    function closeMobileSidebar() {
        sidebar.classList.remove('open');
        if (overlay) overlay.classList.remove('active');
        if (mobileToggle) mobileToggle.setAttribute('aria-expanded', 'false');
    }

    if (mobileToggle && sidebar) {
        mobileToggle.addEventListener('click', () => {
            sidebar.classList.contains('open') ? closeMobileSidebar() : openMobileSidebar();
        });
    }

    if (overlay) {
        overlay.addEventListener('click', closeMobileSidebar);
    }

    // Close sidebar on Escape key
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && sidebar && sidebar.classList.contains('open')) {
            closeMobileSidebar();
        }
    });

    if (toggle && sidebar) {
        // Restore saved collapsed state
        if (localStorage.getItem('rdc-sidebar-collapsed') === 'true') {
            sidebar.classList.add('collapsed');
            if (mainWrapper) mainWrapper.classList.add('sidebar-collapsed');
            toggle.setAttribute('aria-expanded', 'false');
        } else {
            toggle.setAttribute('aria-expanded', 'true');
        }

        toggle.addEventListener('click', () => {
            const isCollapsed = sidebar.classList.toggle('collapsed');
            if (mainWrapper) mainWrapper.classList.toggle('sidebar-collapsed', isCollapsed);
            localStorage.setItem('rdc-sidebar-collapsed', isCollapsed);
            toggle.setAttribute('aria-expanded', String(!isCollapsed));
        });
    }
}

/* ─── DROPDOWNS ──────────────────────────────────────────────── */
function initDropdowns() {
    const notifBtn      = document.getElementById('notificationBtn');
    const notifDropdown = document.getElementById('notifDropdown');
    const userBtn       = document.getElementById('userMenuBtn');
    const userDropdown  = document.getElementById('userDropdown');

    function toggleDropdown(dropdown, btn) {
        const isOpen = dropdown.classList.toggle('active');
        btn.setAttribute('aria-expanded', String(isOpen));
    }

    function closeAll() {
        if (notifDropdown) {
            notifDropdown.classList.remove('active');
            if (notifBtn) notifBtn.setAttribute('aria-expanded', 'false');
        }
        if (userDropdown) {
            userDropdown.classList.remove('active');
            if (userBtn) userBtn.setAttribute('aria-expanded', 'false');
        }
    }

    if (notifBtn && notifDropdown) {
        notifBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            if (userDropdown) {
                userDropdown.classList.remove('active');
                if (userBtn) userBtn.setAttribute('aria-expanded', 'false');
            }
            toggleDropdown(notifDropdown, notifBtn);
        });
    }

    if (userBtn && userDropdown) {
        userBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            if (notifDropdown) {
                notifDropdown.classList.remove('active');
                if (notifBtn) notifBtn.setAttribute('aria-expanded', 'false');
            }
            toggleDropdown(userDropdown, userBtn);
        });
    }

    document.addEventListener('click', closeAll);
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') closeAll();
    });

    // Prevent dropdown close when clicking inside
    [notifDropdown, userDropdown].forEach(dd => {
        if (dd) dd.addEventListener('click', e => e.stopPropagation());
    });
}

/* ─── NOTIFICATIONS ──────────────────────────────────────────── */
let _notifPollInterval = null;

function initNotifications() {
    loadNotificationCount();
    loadRecentNotifications();

    // Poll every 30 s; clean up on page unload
    _notifPollInterval = setInterval(loadNotificationCount, 30000);
    window.addEventListener('pagehide', () => {
        if (_notifPollInterval) clearInterval(_notifPollInterval);
    });

    const markAllBtn = document.getElementById('markAllRead');
    if (markAllBtn) {
        markAllBtn.addEventListener('click', () => {
            const token = getCsrfToken();
            fetch('/notifications/mark-all-read', {
                method: 'POST',
                headers: {
                    'X-CSRFToken': token,
                    'Content-Type': 'application/json',
                },
                credentials: 'same-origin',
            }).then(() => {
                loadNotificationCount();
                loadRecentNotifications();
            }).catch(() => { /* silent fail */ });
        });
    }
}

function loadNotificationCount() {
    fetch('/notifications/api/count', { credentials: 'same-origin' })
        .then(r => r.ok ? r.json() : null)
        .then(data => {
            if (!data) return;
            // Topbar bell badge
            const badge = document.getElementById('notifBadge');
            if (badge) {
                if (data.count > 0) {
                    badge.textContent = data.count > 99 ? '99+' : data.count;
                    badge.style.display = 'flex';
                } else {
                    badge.style.display = 'none';
                }
            }
            // Sidebar nav badge
            const sidebarBadge = document.getElementById('sidebarNotifBadge');
            if (sidebarBadge) {
                if (data.count > 0) {
                    sidebarBadge.textContent = data.count > 99 ? '99+' : data.count;
                    sidebarBadge.style.display = 'inline-flex';
                } else {
                    sidebarBadge.style.display = 'none';
                }
            }
        })
        .catch(() => { /* silent */ });
}

/**
 * SECURITY FIX: Build notification DOM elements safely using
 * createElement/textContent instead of innerHTML with user data.
 * This prevents XSS if notification titles/messages ever contain HTML.
 */
function loadRecentNotifications() {
    const list = document.getElementById('notifList');
    if (!list) return;

    fetch('/notifications/api/recent', { credentials: 'same-origin' })
        .then(r => r.ok ? r.json() : [])
        .then(notifications => {
            // Clear existing content safely
            list.innerHTML = '';

            if (!notifications.length) {
                const empty = document.createElement('div');
                empty.className = 'notif-empty';
                empty.textContent = 'No notifications';
                list.appendChild(empty);
                return;
            }

            notifications.forEach(n => {
                const item = document.createElement('div');
                item.className = 'notif-item' + (n.is_read === 'N' ? ' unread' : '');

                // Safe navigation: validate URL is relative before using
                if (n.link && isRelativeUrl(n.link)) {
                    item.style.cursor = 'pointer';
                    item.addEventListener('click', () => {
                        window.location.href = n.link;
                    });
                    item.setAttribute('role', 'button');
                    item.setAttribute('tabindex', '0');
                    item.addEventListener('keydown', e => {
                        if (e.key === 'Enter' || e.key === ' ') window.location.href = n.link;
                    });
                }

                const dot = document.createElement('div');
                dot.className = 'notif-dot' + (n.is_read === 'Y' ? ' read' : '');

                const text = document.createElement('div');
                text.className = 'notif-text';

                const strong = document.createElement('strong');
                strong.textContent = n.title || 'Notification';   // textContent = safe

                const p = document.createElement('p');
                p.textContent = truncate(n.message, 80);           // textContent = safe

                const small = document.createElement('small');
                small.textContent = n.created_at;                  // textContent = safe

                text.appendChild(strong);
                text.appendChild(p);
                text.appendChild(small);

                item.appendChild(dot);
                item.appendChild(text);
                list.appendChild(item);
            });
        })
        .catch(() => { /* silent */ });
}

/** Returns true only for safe relative URLs (no protocol or host) */
function isRelativeUrl(url) {
    return typeof url === 'string' &&
           url.startsWith('/') &&
           !url.startsWith('//') &&
           !url.startsWith('/\\');
}

function truncate(text, len) {
    if (!text || typeof text !== 'string') return '';
    return text.length > len ? text.substring(0, len) + '…' : text;
}

/** Get CSRF token from hidden form input (Flask-WTF places these in forms) */
function getCsrfToken() {
    const input = document.querySelector('input[name="csrf_token"]');
    return input ? input.value : '';
}

/* ─── FLASH MESSAGES ─────────────────────────────────────────── */
function initFlashMessages() {
    document.querySelectorAll('.flash-message[data-auto-dismiss]').forEach(msg => {
        const delay = parseInt(msg.getAttribute('data-auto-dismiss'), 10);
        if (!delay || isNaN(delay)) return;
        setTimeout(() => {
            msg.style.opacity = '0';
            msg.style.transform = 'translateX(-16px)';
            msg.style.transition = 'opacity 0.25s, transform 0.25s';
            setTimeout(() => msg.remove(), 280);
        }, delay);
    });
}

/* ─── ANIMATED COUNTERS (IntersectionObserver) ───────────────── */
// Phase 6: Only animate when element enters the viewport
function initCounters() {
    const counters = document.querySelectorAll('.kpi-value[data-count]');
    if (!counters.length) return;

    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (!entry.isIntersecting) return;
            observer.unobserve(entry.target); // animate once
            animateCounter(entry.target);
        });
    }, { threshold: 0.2 });

    counters.forEach(el => observer.observe(el));
}

function animateCounter(el) {
    const target   = parseInt(el.getAttribute('data-count'), 10) || 0;
    const prefix   = el.getAttribute('data-prefix') || '';
    const duration = 1000; // 1 s — snappy, not sluggish
    const start    = performance.now();

    function update(timestamp) {
        const elapsed  = timestamp - start;
        const progress = Math.min(elapsed / duration, 1);
        // Ease-out quart — feels premium and decelerates naturally
        const eased  = 1 - Math.pow(1 - progress, 4);
        const current = Math.floor(eased * target);

        el.textContent = prefix === '₹'
            ? '₹' + current.toLocaleString('en-IN')
            : prefix + current.toLocaleString('en-IN');

        if (progress < 1) requestAnimationFrame(update);
    }

    requestAnimationFrame(update);
}

/* ─── PASSWORD TOGGLE ────────────────────────────────────────── */
function initPasswordToggle() {
    const toggleBtn = document.getElementById('passwordToggle');
    if (!toggleBtn) return;

    toggleBtn.addEventListener('click', () => {
        const input     = document.getElementById('password');
        const eyeOpen   = toggleBtn.querySelector('.eye-open');
        const eyeClosed = toggleBtn.querySelector('.eye-closed');
        if (!input) return;

        const showing = input.type === 'password';
        input.type = showing ? 'text' : 'password';
        toggleBtn.setAttribute('aria-label', showing ? 'Hide password' : 'Show password');
        if (eyeOpen)   eyeOpen.style.display   = showing ? 'none'  : 'block';
        if (eyeClosed) eyeClosed.style.display = showing ? 'block' : 'none';
    });
}

/* ─── FORM ENHANCEMENTS ──────────────────────────────────────── */
function initFormEnhancements() {
    // Debounce search inputs so they don't fire on every keystroke
    document.querySelectorAll('input[name="search"]').forEach(input => {
        let timer;
        input.addEventListener('input', () => {
            clearTimeout(timer);
            timer = setTimeout(() => {
                const form = input.closest('form');
                // Only auto-submit if the input has 0 or ≥3 chars (avoids mid-word fetches)
                if (form && (input.value.length === 0 || input.value.length >= 3)) {
                    // Don't auto-submit — just style the input to indicate activity
                    input.style.borderColor = input.value ? 'var(--accent-primary)' : '';
                }
            }, 300);
        });
    });

    // Add loading state to forms on submit
    document.querySelectorAll('form').forEach(form => {
        form.addEventListener('submit', function () {
            const submitBtn = form.querySelector('[type="submit"]');
            if (submitBtn && !submitBtn.dataset.noLoadingState) {
                submitBtn.disabled = true;
                const original = submitBtn.innerHTML;
                submitBtn.dataset.originalContent = original;
                // Re-enable after 10 s as a safety net
                setTimeout(() => {
                    submitBtn.disabled = false;
                    submitBtn.innerHTML = submitBtn.dataset.originalContent || original;
                }, 10000);
            }
        });
    });
}

/* ─── MOUSE SPOTLIGHT ────────────────────────────────────────── */
/**
 * Injects a fixed radial-gradient overlay that tracks the cursor.
 * Only activates on pointer:fine (mouse) devices — skips touch screens.
 * The gradient position is driven by CSS custom properties --mx / --my
 * set on the spotlight element, which the CSS background formula reads.
 */
function initMouseSpotlight() {
    // Skip on touch-only devices
    if (!window.matchMedia('(pointer: fine)').matches) return;

    const el = document.createElement('div');
    el.id = 'mouse-spotlight';
    document.body.appendChild(el);

    let rafPending = false;
    let curX = -9999, curY = -9999;

    document.addEventListener('mousemove', (e) => {
        curX = e.clientX;
        curY = e.clientY;
        if (rafPending) return;
        rafPending = true;
        requestAnimationFrame(() => {
            el.style.setProperty('--mx', curX + 'px');
            el.style.setProperty('--my', curY + 'px');
            rafPending = false;
        });
    });

    // Fade in on first move, fade out when cursor leaves the window
    document.addEventListener('mousemove', () => {
        if (!el.classList.contains('active')) el.classList.add('active');
    }, { once: false, passive: true });

    document.addEventListener('mouseleave', () => {
        el.classList.remove('active');
    });
}

/* ─── SCROLL REVEAL ──────────────────────────────────────────── */
/**
 * Adds .reveal to every .content-card and .kpi-card on the page,
 * then uses IntersectionObserver to add .is-visible as each enters
 * the viewport. Cards are staggered in batches of 4 (60 ms each).
 * Cleans up transition-delay after the animation fires so hover
 * transitions aren't affected.
 */
function initScrollReveal() {
    if (!('IntersectionObserver' in window)) return;

    const items = document.querySelectorAll('.content-card, .kpi-card');
    if (!items.length) return;

    // Assign .reveal + stagger delay grouped in rows of 4
    items.forEach((el, i) => {
        el.classList.add('reveal');
        el.style.transitionDelay = ((i % 4) * 65) + 'ms';
    });

    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (!entry.isIntersecting) return;
            entry.target.classList.add('is-visible');
            observer.unobserve(entry.target);
            // Remove delay after animation so hover works instantly
            setTimeout(() => {
                entry.target.style.transitionDelay = '';
            }, 650);
        });
    }, {
        threshold: 0.07,
        rootMargin: '0px 0px -24px 0px',
    });

    // Observe — but also trigger immediately for anything already in viewport
    items.forEach(el => {
        observer.observe(el);
        const r = el.getBoundingClientRect();
        if (r.top < window.innerHeight && r.bottom > 0) {
            // Already visible on load — animate right away (no extra delay)
            el.style.transitionDelay = '0ms';
            requestAnimationFrame(() => {
                el.classList.add('is-visible');
                observer.unobserve(el);
                setTimeout(() => { el.style.transitionDelay = ''; }, 650);
            });
        }
    });
}

/* ─── BUTTON RIPPLE ──────────────────────────────────────────── */
/**
 * Adds a Material-style ripple to every .btn on click.
 * A <span class="btn-ripple-el"> is sized relative to the button,
 * positioned at the click point, and removed after its CSS animation
 * completes. Works on dynamically added buttons via event delegation.
 */
function initButtonRipple() {
    document.addEventListener('click', (e) => {
        const btn = e.target.closest('.btn');
        if (!btn || btn.disabled) return;

        const rect   = btn.getBoundingClientRect();
        const size   = Math.max(rect.width, rect.height) * 1.6;
        const x      = e.clientX - rect.left  - size / 2;
        const y      = e.clientY - rect.top   - size / 2;

        // Ensure the button clips the ripple
        if (getComputedStyle(btn).position === 'static') {
            btn.style.position = 'relative';
        }
        if (getComputedStyle(btn).overflow !== 'hidden') {
            btn.style.overflow = 'hidden';
        }

        const ripple = document.createElement('span');
        ripple.className = 'btn-ripple-el';
        ripple.style.cssText =
            `width:${size}px;height:${size}px;left:${x}px;top:${y}px;`;

        btn.appendChild(ripple);
        ripple.addEventListener('animationend', () => ripple.remove(), { once: true });
    });
}
