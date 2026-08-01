/**
 * Injects a "Migrate" tab into aaPanel's website Settings modal, letting the
 * user pull files into THIS site's web root from a remote server over SSH
 * (rsync), without having to leave the modal or pick a destination website
 * (the modal is already scoped to one site).
 *
 * Targets the modern aaPanel UI (Vue 3 + naive-ui, Vite build -- no jQuery
 * or layui available here), where the Settings modal looks like:
 *
 *   <div class="n-dialog">
 *     <div class="n-dialog__title">Site modification [example.com] -- ...</div>
 *     <div class="n-dialog__content">
 *       <div class="overflow-auto">
 *         <div class="h-full">
 *           <div class="n-tabs n-tabs--left bt-tabs-modal">   <- outerTabs
 *             <div class="n-tabs-nav">                        <- left-side tab menu
 *               <div class="n-tabs-wrapper">
 *                 <div class="n-tabs-tab-wrapper">
 *                   <div data-name="domain" class="n-tabs-tab">...
 *                 ... (directory, access, rewrite, document, config, ssl,
 *                      php, webserver, git, composer, redirect, proxy,
 *                      hotlink, maintenance, logs)
 *             <div class="n-tab-pane">                         <- active tab's content;
 *                                                                  a DIRECT CHILD of
 *                                                                  outerTabs, sibling
 *                                                                  of the nav div above
 *
 * We add our own tab item into the left-side menu, and our own pane as a
 * sibling of `.n-tab-pane` (both children of outerTabs), toggling visibility
 * between them on click. We never touch the real `.n-tab-pane` content itself
 * (Vue owns it), only its inline `display` style. Nested tab groups (e.g. the
 * Response log sub-tabs) have their own `.n-tab-pane` too, so lookups are
 * scoped to a direct child of outerTabs to avoid matching those instead.
 *
 * If a future aaPanel version changes this markup, the tab simply won't
 * appear (attach() bails out early when the expected nodes aren't found) --
 * the plugin's own admin page (index.html) still works regardless, since it
 * talks to the same backend without depending on this injection.
 */
(function () {
    'use strict';

    var PLUGIN_NAME = 'antweb_ssh_migrate';
    var CUSTOM_TAB_NAME = 'antweb_ssh_migrate_tab';
    var DEFAULT_EXCLUDES = ['.git', 'node_modules', 'vendor'];
    // Bump on every debug-relevant change so it's obvious from the console
    // whether a stale/cached copy of this script is actually running.
    var DEBUG_BUILD = 'debug-6';

    // Forces every sibling .n-tab-pane other than ours to stay hidden while
    // our tab is active, regardless of how many there are (a second plugin
    // can inject its own pane the same way we do, e.g. env_editor's
    // "env-editor-pane") or whether Vue re-asserts its own inline display
    // style on the real pane sometime after we set it -- !important beats
    // both a plain inline style set once and whatever specificity Vue uses.
    function ensureHideStyle() {
        if (document.getElementById('antweb-migrate-hide-style')) return;
        var style = document.createElement('style');
        style.id = 'antweb-migrate-hide-style';
        style.textContent = '.migrate-tab-active > .n-tab-pane:not(.migrate-pane) { display: none !important; }';
        document.head.appendChild(style);
    }

    var DEBUG = true;
    function dlog() {
        // console.log, not console.debug -- Chrome DevTools hides
        // console.debug output under the "Verbose" level, which is off by
        // default, so it silently looks like nothing is running.
        if (!DEBUG || !window.console) return;
        var args = ['[antweb_ssh_migrate ' + DEBUG_BUILD + ']'].concat(Array.prototype.slice.call(arguments));
        console.log.apply(console, args);
    }

    dlog('site_tab.js loaded, MutationObserver supported =', !!window.MutationObserver);
    ensureHideStyle();

    function getCsrfToken() {
        var el = document.getElementById('request_token_head');
        return el ? el.getAttribute('token') : null;
    }

    function requestPlugin(method, args, callback) {
        var body = new URLSearchParams(args || {}).toString();
        var headers = { 'Content-Type': 'application/x-www-form-urlencoded' };
        var token = getCsrfToken();
        if (token) headers['X-Http-Token'] = token;

        fetch('/plugin?action=a&s=' + method + '&name=' + PLUGIN_NAME, {
            method: 'POST',
            headers: headers,
            body: body,
            credentials: 'same-origin'
        })
            .then(function (res) { return res.json(); })
            .then(function (data) {
                if (typeof data === 'string') {
                    try { data = JSON.parse(data); } catch (e) { /* leave as string */ }
                }
                callback(data);
            })
            .catch(function () { callback({ status: false, msg: 'Request failed' }); });
    }

    // The dialog title looks like "Site modification [example.com] -- Time added [...]"
    function extractSiteName(dialogEl) {
        var titleEl = dialogEl.querySelector('.n-dialog__title');
        var titleText = titleEl ? titleEl.textContent : '';
        var m = titleText.match(/\[([^\]]+)\]/);
        return m ? m[1] : null;
    }

    // Native <select>/<option> elements paint their own opaque background
    // regardless of the surrounding page, so we need a real (non-transparent)
    // background color to set explicitly rather than relying on inheritance.
    function getEffectiveBackground(el) {
        while (el) {
            var bg = window.getComputedStyle(el).backgroundColor;
            if (bg && bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent') return bg;
            el = el.parentElement;
        }
        return '#fff';
    }

    // naive-ui bakes a literal "-dark-" substring into hashed component
    // classes when the dark theme is active, so we can detect the theme
    // without guessing at CSS variables, and pull real colors from the
    // dialog itself.
    function applyTheme(dialogEl, pane) {
        var dark = /-dark-/.test(dialogEl.className);
        var textColor = window.getComputedStyle(dialogEl).color;
        var bg = getEffectiveBackground(dialogEl);
        var borderColor = dark ? 'rgba(255,255,255,0.15)' : 'rgba(0,0,0,0.15)';
        var mutedBorder = dark ? 'rgba(255,255,255,0.3)' : 'rgba(0,0,0,0.3)';

        pane.style.color = textColor;

        var inputs = pane.querySelectorAll('.mig-input, .mig-select');
        for (var i = 0; i < inputs.length; i++) {
            inputs[i].style.color = textColor;
            inputs[i].style.background = bg;
            inputs[i].style.border = '1px solid ' + borderColor;
        }

        var secondaryBtns = pane.querySelectorAll('.mig-btn-secondary');
        for (var j = 0; j < secondaryBtns.length; j++) {
            secondaryBtns[j].style.color = textColor;
            secondaryBtns[j].style.border = '1px solid ' + mutedBorder;
        }

        var chips = pane.querySelectorAll('.mig-chip');
        for (var k = 0; k < chips.length; k++) {
            chips[k].style.color = textColor;
            chips[k].style.border = '1px solid ' + borderColor;
        }

        var box = pane.querySelector('.mig-custom-box');
        if (box) box.style.border = '1px dashed ' + borderColor;

        var telemetry = pane.querySelector('.mig-transfer-panel');
        if (telemetry) {
            telemetry.style.background = bg;
            telemetry.style.border = '1px solid ' + borderColor;
        }

        var console_ = pane.querySelector('.mig-console');
        if (console_) console_.style.border = '1px solid ' + borderColor;

        return { dark: dark, textColor: textColor, bg: bg, borderColor: borderColor };
    }

    function chipHtml(label, dataAttr, active) {
        return '<span class="mig-chip' + (active ? ' mig-chip-active' : '') + '" ' + dataAttr + ' ' +
            'style="cursor:pointer;font-size:11px;padding:3px 9px;border-radius:100px;opacity:' + (active ? '1' : '0.55') + ';">' +
            label + '</span>';
    }

    function buildPaneEl() {
        var pane = document.createElement('div');
        pane.className = 'n-tab-pane migrate-pane';
        pane.style.padding = '16px';
        pane.style.display = 'none';
        pane.style.position = 'relative';

        var excludeChips = DEFAULT_EXCLUDES.map(function (v) {
            return chipHtml(v, 'data-val="' + v + '"', true);
        }).join('');

        pane.innerHTML = '' +
            '<div class="mig-form" style="max-height:640px;overflow-y:auto;padding-right:6px;">' +
            '<p style="font-size:12px;opacity:0.65;margin:0 0 14px;">Pull files for this website from a remote server over SSH using rsync. ' +
            'The destination is always this site\'s own web root.</p>' +

            '<div style="margin-bottom:14px;">' +
            '<label style="display:block;font-size:12px;font-weight:600;margin-bottom:6px;">SSH Source Node</label>' +
            '<div style="display:flex;gap:8px;align-items:center;">' +
            '<select class="mig-select mig-node-select" style="flex:1;height:32px;border-radius:6px;">' +
            '<option value="">-- Loading nodes... --</option></select>' +
            '<button type="button" class="mig-btn mig-btn-secondary mig-refresh-nodes" title="Refresh nodes list" ' +
            'style="height:32px;padding:0 10px;border-radius:6px;background:transparent;cursor:pointer;">&#8635;</button>' +
            '</div>' +
            '<label style="display:flex;align-items:center;gap:8px;margin-top:8px;font-size:12px;opacity:0.75;cursor:pointer;">' +
            '<input type="checkbox" class="mig-custom-toggle"> Use custom SSH parameters' +
            '</label>' +
            '</div>' +

            '<div class="mig-custom-box" style="display:none;border-radius:8px;padding:14px;margin-bottom:14px;">' +
            '<div style="display:flex;gap:10px;margin-bottom:10px;">' +
            '<div style="flex:2;"><label style="display:block;font-size:12px;margin-bottom:4px;">Host / IP</label>' +
            '<input type="text" class="mig-input mig-host" style="width:100%;height:30px;box-sizing:border-box;border-radius:6px;padding:0 8px;" placeholder="192.168.1.10"></div>' +
            '<div style="flex:1;"><label style="display:block;font-size:12px;margin-bottom:4px;">Port</label>' +
            '<input type="number" class="mig-input mig-port" style="width:100%;height:30px;box-sizing:border-box;border-radius:6px;padding:0 8px;" value="22"></div>' +
            '<div style="flex:1;"><label style="display:block;font-size:12px;margin-bottom:4px;">User</label>' +
            '<input type="text" class="mig-input mig-user" style="width:100%;height:30px;box-sizing:border-box;border-radius:6px;padding:0 8px;" value="root"></div>' +
            '</div>' +
            '<div style="margin-bottom:10px;"><label style="display:block;font-size:12px;margin-bottom:4px;">Auth Type</label>' +
            '<select class="mig-select mig-auth-type" style="width:100%;height:30px;border-radius:6px;">' +
            '<option value="password">Password</option><option value="key">Private Key</option></select></div>' +
            '<div class="mig-password-group" style="margin-bottom:10px;">' +
            '<label style="display:block;font-size:12px;margin-bottom:4px;">Password</label>' +
            '<input type="password" class="mig-input mig-password" style="width:100%;height:30px;box-sizing:border-box;border-radius:6px;padding:0 8px;"></div>' +
            '<div class="mig-key-group" style="display:none;margin-bottom:10px;">' +
            '<label style="display:block;font-size:12px;margin-bottom:4px;">Private Key</label>' +
            '<textarea class="mig-input mig-key" rows="4" style="width:100%;box-sizing:border-box;border-radius:6px;padding:8px;font-family:Consolas,Monaco,monospace;font-size:12px;" ' +
            'placeholder="-----BEGIN OPENSSH PRIVATE KEY-----"></textarea></div>' +
            '<div style="display:flex;align-items:center;gap:10px;">' +
            '<button type="button" class="mig-btn mig-btn-secondary mig-test-conn" ' +
            'style="padding:6px 14px;border-radius:6px;background:transparent;cursor:pointer;">Test Connection</button>' +
            '<span class="mig-test-status" style="font-size:12px;"></span>' +
            '</div>' +
            '</div>' +

            '<div style="margin-bottom:14px;">' +
            '<label style="display:block;font-size:12px;font-weight:600;margin-bottom:6px;">Remote Source Path</label>' +
            '<input type="text" class="mig-input mig-remote-dir" style="width:100%;height:32px;box-sizing:border-box;border-radius:6px;padding:0 8px;" placeholder="/www/wwwroot/my_site">' +
            '<div style="display:flex;gap:6px;margin-top:6px;flex-wrap:wrap;">' +
            chipHtml('/www/wwwroot/', 'data-fill="/www/wwwroot/"', false) +
            chipHtml('/root/', 'data-fill="/root/"', false) +
            chipHtml('/home/', 'data-fill="/home/"', false) +
            '</div>' +
            '</div>' +

            '<div style="margin-bottom:14px;">' +
            '<label style="display:block;font-size:12px;font-weight:600;margin-bottom:6px;">Destination (this website)</label>' +
            '<div class="mig-dest-hint" style="font-family:Consolas,Monaco,monospace;font-size:12px;opacity:0.75;">Resolving website path...</div>' +
            '</div>' +

            '<div style="margin-bottom:14px;">' +
            '<label style="display:block;font-size:12px;font-weight:600;margin-bottom:6px;">Exclude Folders</label>' +
            '<input type="text" class="mig-input mig-exclude" style="width:100%;height:32px;box-sizing:border-box;border-radius:6px;padding:0 8px;" value="' + DEFAULT_EXCLUDES.join(', ') + '">' +
            '<div class="mig-exclude-chips" style="display:flex;gap:6px;margin-top:6px;flex-wrap:wrap;">' + excludeChips + '</div>' +
            '</div>' +

            '<div style="display:flex;gap:20px;margin-bottom:16px;flex-wrap:wrap;">' +
            '<label style="display:flex;align-items:center;gap:8px;font-size:12px;cursor:pointer;"><input type="checkbox" class="mig-sync-mode"> Sync Mode (delete local extras)</label>' +
            '<label style="display:flex;align-items:center;gap:8px;font-size:12px;cursor:pointer;"><input type="checkbox" class="mig-overwrite" checked> Overwrite existing</label>' +
            '</div>' +

            '<button type="button" class="mig-btn mig-btn-primary mig-start-btn" ' +
            'style="width:100%;padding:9px 0;border:none;border-radius:6px;background:#1a94ff;color:#fff;font-weight:600;cursor:pointer;">Start Migration</button>' +
            '<button type="button" class="mig-btn mig-btn-secondary mig-history-btn" ' +
            'style="width:100%;padding:7px 0;margin-top:8px;border-radius:6px;background:transparent;cursor:pointer;">View Transfer History</button>' +
            '</div>' +

            '<div class="mig-transfer-panel" style="display:none;position:absolute;top:0;left:0;right:0;bottom:0;border-radius:8px;padding:18px;box-sizing:border-box;flex-direction:column;justify-content:space-between;overflow-y:auto;">' +
            '<div>' +
            '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">' +
            '<span style="font-weight:700;font-size:13px;">Migration Telemetry</span>' +
            '<span class="mig-status-badge" style="font-size:11px;font-weight:600;padding:3px 8px;border-radius:100px;background:rgba(245,158,11,0.15);color:#f59e0b;">RUNNING</span>' +
            '</div>' +
            '<div style="height:8px;border-radius:8px;background:rgba(128,128,128,0.2);overflow:hidden;margin-bottom:12px;">' +
            '<div class="mig-progress-bar" style="height:100%;width:0%;background:#1a94ff;border-radius:8px;transition:width .4s ease;"></div>' +
            '</div>' +
            '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:12px;">' +
            '<div style="text-align:center;"><div style="font-size:10px;opacity:0.6;text-transform:uppercase;">Progress</div><div class="mig-metric-progress" style="font-size:14px;font-weight:600;">0%</div></div>' +
            '<div style="text-align:center;"><div style="font-size:10px;opacity:0.6;text-transform:uppercase;">Speed</div><div class="mig-metric-speed" style="font-size:14px;font-weight:600;">--</div></div>' +
            '<div style="text-align:center;"><div style="font-size:10px;opacity:0.6;text-transform:uppercase;">ETA</div><div class="mig-metric-eta" style="font-size:14px;font-weight:600;">--:--:--</div></div>' +
            '</div>' +
            '<label style="display:block;font-size:11px;opacity:0.6;margin-bottom:4px;">Console Log</label>' +
            '<div class="mig-console" style="background:rgba(0,0,0,0.75);color:#fca5a5;border-radius:6px;padding:10px;height:220px;overflow-y:auto;font-family:Consolas,Monaco,monospace;font-size:11.5px;line-height:1.5;"></div>' +
            '</div>' +
            '<div style="display:flex;gap:10px;justify-content:flex-end;margin-top:14px;">' +
            '<button type="button" class="mig-btn mig-cancel-btn" style="padding:7px 16px;border:none;border-radius:6px;background:#ed4014;color:#fff;cursor:pointer;">Abort</button>' +
            '<button type="button" class="mig-btn mig-close-panel-btn" style="display:none;padding:7px 16px;border:none;border-radius:6px;background:rgba(128,128,128,0.3);cursor:pointer;">Close</button>' +
            '</div>' +
            '</div>';
        return pane;
    }

    // Small self-contained overlay (no layer.js/jQuery available in this
    // context) used for the transfer history list and per-task log viewer.
    function openOverlay(theme, title) {
        var backdrop = document.createElement('div');
        backdrop.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.5);z-index:9999;display:flex;align-items:center;justify-content:center;';

        var box = document.createElement('div');
        box.style.cssText = 'width:640px;max-width:90vw;max-height:80vh;display:flex;flex-direction:column;' +
            'background:' + (theme.dark ? '#1e1e1e' : '#fff') + ';color:' + theme.textColor + ';' +
            'border-radius:10px;box-shadow:0 20px 50px rgba(0,0,0,0.4);overflow:hidden;';

        var header = document.createElement('div');
        header.style.cssText = 'display:flex;justify-content:space-between;align-items:center;padding:14px 18px;border-bottom:1px solid ' + theme.borderColor + ';flex-shrink:0;';
        header.innerHTML = '<span style="font-weight:700;font-size:14px;">' + title + '</span>' +
            '<span class="mig-overlay-close" style="cursor:pointer;font-size:16px;opacity:0.6;">&times;</span>';

        var body = document.createElement('div');
        body.style.cssText = 'padding:16px 18px;overflow-y:auto;flex-grow:1;';

        box.appendChild(header);
        box.appendChild(body);
        backdrop.appendChild(box);
        document.body.appendChild(backdrop);

        function close() { if (backdrop.parentNode) backdrop.parentNode.removeChild(backdrop); }
        header.querySelector('.mig-overlay-close').addEventListener('click', close);
        backdrop.addEventListener('click', function (e) { if (e.target === backdrop) close(); });

        return { body: body, close: close };
    }

    function attach(dialogEl) {
        if (dialogEl.dataset.migrateAttached) return;

        // "n-tabs--left.bt-tabs-modal" is a generic left-tabs modal layout
        // aaPanel reuses for several settings dialogs (FTP, database, cron,
        // ...), not just the website Settings modal, so it isn't a specific
        // enough signal on its own. The "domain" tab is unique to the site
        // config panel (nested sub-tabs like Response log use
        // "n-tabs--top"/"bt-tabs" instead, so this won't match those either).
        var outerTabs = dialogEl.querySelector('.n-tabs--left.bt-tabs-modal');
        if (!outerTabs) {
            dlog('bailed: no .n-tabs--left.bt-tabs-modal inside dialog', dialogEl);
            return; // not a left-tabs modal at all
        }
        if (!outerTabs.querySelector('[data-name="domain"]')) {
            dlog('bailed: outerTabs found but no domain tab -- not the website Settings modal', outerTabs);
            return;
        }

        var tabsWrapper = outerTabs.querySelector('.n-tabs-wrapper');
        var tabPane = null;
        for (var i = 0; i < outerTabs.children.length; i++) {
            if (outerTabs.children[i].classList.contains('n-tab-pane')) {
                tabPane = outerTabs.children[i];
                break;
            }
        }
        if (!tabsWrapper || !tabPane) {
            dlog('bailed: found outerTabs but missing', { tabsWrapper: !!tabsWrapper, tabPane: !!tabPane }, outerTabs);
            return;
        }

        var initialChildren = [];
        for (var ci = 0; ci < outerTabs.children.length; ci++) {
            var c = outerTabs.children[ci];
            initialChildren.push({ index: ci, tag: c.tagName, className: c.className, inlineDisplay: c.style.display, computedDisplay: window.getComputedStyle(c).display });
        }
        dlog('attaching Migrate tab. outerTabs.children at attach time = ' + JSON.stringify(initialChildren));
        dialogEl.dataset.migrateAttached = 'true';

        var siteName = extractSiteName(dialogEl);

        var tabItem = document.createElement('div');
        tabItem.className = 'n-tabs-tab-wrapper';
        tabItem.innerHTML = '<div class="n-tabs-tab-pad"></div>' +
            '<div data-name="' + CUSTOM_TAB_NAME + '" class="n-tabs-tab">' +
            '<span class="n-tabs-tab__label">Migrate</span>' +
            '</div>';

        var scrollPads = tabsWrapper.querySelectorAll('.n-tabs-scroll-padding');
        var lastScrollPad = scrollPads.length ? scrollPads[scrollPads.length - 1] : null;
        if (lastScrollPad) {
            tabsWrapper.insertBefore(tabItem, lastScrollPad);
        } else {
            tabsWrapper.appendChild(tabItem);
        }

        var ourPane = buildPaneEl();
        tabPane.parentNode.insertBefore(ourPane, tabPane.nextSibling);

        var theme = applyTheme(dialogEl, ourPane);

        var nodeSelect = ourPane.querySelector('.mig-node-select');
        var refreshNodesBtn = ourPane.querySelector('.mig-refresh-nodes');
        var customToggle = ourPane.querySelector('.mig-custom-toggle');
        var customBox = ourPane.querySelector('.mig-custom-box');
        var authType = ourPane.querySelector('.mig-auth-type');
        var passwordGroup = ourPane.querySelector('.mig-password-group');
        var keyGroup = ourPane.querySelector('.mig-key-group');
        var testBtn = ourPane.querySelector('.mig-test-conn');
        var testStatus = ourPane.querySelector('.mig-test-status');
        var remoteDirInput = ourPane.querySelector('.mig-remote-dir');
        var destHint = ourPane.querySelector('.mig-dest-hint');
        var excludeInput = ourPane.querySelector('.mig-exclude');
        var syncMode = ourPane.querySelector('.mig-sync-mode');
        var overwrite = ourPane.querySelector('.mig-overwrite');
        var startBtn = ourPane.querySelector('.mig-start-btn');
        var historyBtn = ourPane.querySelector('.mig-history-btn');
        var form = ourPane.querySelector('.mig-form');
        var transferPanel = ourPane.querySelector('.mig-transfer-panel');
        var progressBar = ourPane.querySelector('.mig-progress-bar');
        var metricProgress = ourPane.querySelector('.mig-metric-progress');
        var metricSpeed = ourPane.querySelector('.mig-metric-speed');
        var metricEta = ourPane.querySelector('.mig-metric-eta');
        var statusBadge = ourPane.querySelector('.mig-status-badge');
        var consoleEl = ourPane.querySelector('.mig-console');
        var cancelBtn = ourPane.querySelector('.mig-cancel-btn');
        var closePanelBtn = ourPane.querySelector('.mig-close-panel-btn');

        var loaded = false;
        var resolvedLocalDir = null;
        var activeTaskId = null;
        var pollTimer = null;

        function activateOurs() {
            var tabs = tabsWrapper.querySelectorAll('.n-tabs-tab');
            for (var i = 0; i < tabs.length; i++) tabs[i].classList.remove('n-tabs-tab--active');
            tabItem.querySelector('.n-tabs-tab').classList.add('n-tabs-tab--active');

            // Force-hide every other .n-tab-pane sibling via the injected
            // !important stylesheet rule (see ensureHideStyle()) instead of
            // imperatively setting one specific node's inline style. This
            // covers cases an imperative "find the one active pane and hide
            // it" approach can't: more than one sibling pane simultaneously
            // present (e.g. another plugin's own injected tab, such as
            // env_editor's "env-editor-pane"), and Vue re-asserting its own
            // inline display style on the real pane after we set it.
            outerTabs.classList.add('migrate-tab-active');
            ourPane.style.display = '';

            if (!loaded) {
                loaded = true;
                loadNodes();
                resolveDestination();
            }
        }

        function deactivateOurs() {
            var activeTabEl = tabItem.querySelector('.n-tabs-tab');
            if (activeTabEl) activeTabEl.classList.remove('n-tabs-tab--active');
            ourPane.style.display = 'none';
            outerTabs.classList.remove('migrate-tab-active');
        }

        function loadNodes() {
            nodeSelect.innerHTML = '<option value="">-- Refreshing nodes... --</option>';
            requestPlugin('get_ssh_nodes', {}, function (data) {
                if (!data || !data.status) {
                    nodeSelect.innerHTML = '<option value="">Error: ' + ((data && (data.message || data.msg)) || 'failed to load nodes') + '</option>';
                    return;
                }
                var list = data.data || [];
                if (!list.length) {
                    nodeSelect.innerHTML = '<option value="">No saved SSH nodes found. Use custom parameters below.</option>';
                    return;
                }
                var opts = '<option value="">-- Choose a saved SSH node --</option>';
                list.forEach(function (n) {
                    opts += '<option value="' + n.id + '">' + n.remark + ' (' + n.host + ':' + n.port + ')</option>';
                });
                nodeSelect.innerHTML = opts;
            });
        }

        function resolveDestination() {
            if (!siteName) {
                destHint.textContent = 'Could not detect the site name from the dialog title.';
                startBtn.disabled = true;
                return;
            }
            requestPlugin('get_websites', {}, function (data) {
                if (!data || !data.status) {
                    destHint.textContent = 'Failed to resolve this site\'s path: ' + ((data && (data.message || data.msg)) || 'unknown error');
                    startBtn.disabled = true;
                    return;
                }
                var list = data.data || [];
                var match = null;
                for (var i = 0; i < list.length; i++) {
                    if (list[i].name === siteName) { match = list[i]; break; }
                }
                if (!match) {
                    destHint.textContent = 'Could not find a registered website matching "' + siteName + '".';
                    startBtn.disabled = true;
                    return;
                }
                resolvedLocalDir = match.path;
                destHint.textContent = resolvedLocalDir;
                startBtn.disabled = false;
            });
        }

        customToggle.addEventListener('change', function () {
            if (this.checked) {
                nodeSelect.disabled = true;
                customBox.style.display = '';
            } else {
                nodeSelect.disabled = false;
                customBox.style.display = 'none';
            }
        });

        authType.addEventListener('change', function () {
            if (this.value === 'key') {
                passwordGroup.style.display = 'none';
                keyGroup.style.display = '';
            } else {
                passwordGroup.style.display = '';
                keyGroup.style.display = 'none';
            }
        });

        nodeSelect.addEventListener('change', function () {
            if (this.value) {
                customToggle.checked = false;
                customBox.style.display = 'none';
            }
        });

        refreshNodesBtn.addEventListener('click', loadNodes);

        ourPane.querySelectorAll('[data-fill]').forEach(function (chip) {
            chip.addEventListener('click', function () {
                var path = chip.getAttribute('data-fill');
                var current = remoteDirInput.value || '/';
                if (current === '/' || current.indexOf(path) !== 0) remoteDirInput.value = path;
            });
        });

        ourPane.querySelectorAll('.mig-exclude-chips .mig-chip').forEach(function (chip) {
            chip.addEventListener('click', function () {
                var active = chip.classList.toggle('mig-chip-active');
                chip.style.opacity = active ? '1' : '0.55';
                var val = chip.getAttribute('data-val');
                var current = excludeInput.value.split(',').map(function (s) { return s.trim(); }).filter(function (s) { return s; });
                var idx = current.indexOf(val);
                if (active && idx === -1) current.push(val);
                else if (!active && idx > -1) current.splice(idx, 1);
                excludeInput.value = current.join(', ');
            });
        });

        function gatherSshArgs() {
            var args = {};
            if (customToggle.checked) {
                args.host = ourPane.querySelector('.mig-host').value.trim();
                args.port = ourPane.querySelector('.mig-port').value.trim();
                args.username = ourPane.querySelector('.mig-user').value.trim();
                args.auth_type = authType.value;
                args.password = ourPane.querySelector('.mig-password').value.trim();
                args.key = ourPane.querySelector('.mig-key').value.trim();
                if (!args.host) return { error: 'Host IP is required for custom connection.' };
            } else {
                var nodeId = nodeSelect.value;
                if (!nodeId) return { error: 'Please select a saved SSH node, or enable custom parameters.' };
                args.node_id = nodeId;
            }
            return { args: args };
        }

        testBtn.addEventListener('click', function () {
            var res = gatherSshArgs();
            if (res.error) {
                testStatus.textContent = res.error;
                testStatus.style.color = '#ed4014';
                return;
            }
            testStatus.textContent = 'Testing...';
            testStatus.style.color = theme.textColor;
            requestPlugin('test_connection', res.args, function (data) {
                var msg = (data && (data.message || data.msg)) || 'Connection check completed.';
                testStatus.textContent = msg;
                testStatus.style.color = (data && data.status) ? '#19be6b' : '#ed4014';
            });
        });

        function setStatusBadge(label, bg, color) {
            statusBadge.textContent = label;
            statusBadge.style.background = bg;
            statusBadge.style.color = color;
        }

        function appendLogs(rawLogs) {
            if (!rawLogs) return;
            var lines = rawLogs.split('\n');
            var html = '';
            lines.forEach(function (line) {
                if (!line) return;
                var color = '#fca5a5';
                if (line.indexOf('Error') > -1 || line.indexOf('failed') > -1) color = '#ef4444';
                else if (line.indexOf('completed successfully') > -1) color = '#10b981';
                html += '<div style="margin-bottom:3px;white-space:pre-wrap;color:' + color + ';">' + line + '</div>';
            });
            consoleEl.innerHTML = html;
            consoleEl.scrollTop = consoleEl.scrollHeight;
        }

        function stopPolling() {
            if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
        }

        function pollStatus() {
            stopPolling();
            pollTimer = setInterval(function () {
                if (!activeTaskId) { stopPolling(); return; }
                requestPlugin('get_task_status', { task_id: activeTaskId }, function (data) {
                    if (!data || !data.status) return;
                    var pct = data.progress + '%';
                    progressBar.style.width = pct;
                    metricProgress.textContent = pct;
                    metricSpeed.textContent = data.speed || '--';
                    metricEta.textContent = data.eta || '--:--:--';
                    appendLogs(data.logs);

                    if (data.task_status === 'success') {
                        stopPolling();
                        setStatusBadge('SUCCESS', 'rgba(16,185,129,0.15)', '#10b981');
                        cancelBtn.style.display = 'none';
                        closePanelBtn.style.display = '';
                    } else if (data.task_status === 'error') {
                        stopPolling();
                        setStatusBadge('ERROR', 'rgba(239,68,68,0.15)', '#ef4444');
                        cancelBtn.style.display = 'none';
                        closePanelBtn.style.display = '';
                        if (data.error) appendLogs('Process Aborted: ' + data.error);
                    }
                });
            }, 1500);
        }

        startBtn.addEventListener('click', function () {
            if (!resolvedLocalDir) {
                testStatus.textContent = 'Destination path is not resolved yet.';
                return;
            }
            var remoteDir = remoteDirInput.value.trim();
            if (!remoteDir) {
                remoteDirInput.focus();
                return;
            }
            var res = gatherSshArgs();
            if (res.error) {
                testStatus.textContent = res.error;
                testStatus.style.color = '#ed4014';
                return;
            }
            var args = res.args;
            args.remote_dir = remoteDir;
            args.local_dir = resolvedLocalDir;
            args.exclude_folders = excludeInput.value.trim();
            args.sync_mode = syncMode.checked ? 1 : 0;
            args.overwrite = overwrite.checked ? 1 : 0;

            var warn = syncMode.checked ?
                ' Sync Mode will delete files already in ' + resolvedLocalDir + ' that do not exist remotely.' : '';
            if (!window.confirm('Migrate files from the remote server into ' + resolvedLocalDir + '?' + warn)) return;

            startBtn.disabled = true;
            requestPlugin('start_copy', args, function (data) {
                startBtn.disabled = false;
                if (!data || !data.status) {
                    testStatus.textContent = (data && (data.message || data.msg)) || 'Failed to start migration.';
                    testStatus.style.color = '#ed4014';
                    return;
                }
                activeTaskId = data.data.task_id;
                form.style.display = 'none';
                transferPanel.style.display = 'flex';
                progressBar.style.width = '0%';
                metricProgress.textContent = '0%';
                metricSpeed.textContent = '--';
                metricEta.textContent = '--:--:--';
                setStatusBadge('RUNNING', 'rgba(245,158,11,0.15)', '#f59e0b');
                consoleEl.innerHTML = '';
                cancelBtn.style.display = '';
                closePanelBtn.style.display = 'none';
                pollStatus();
            });
        });

        cancelBtn.addEventListener('click', function () {
            if (!activeTaskId) return;
            if (!window.confirm('Force terminate the current migration?')) return;
            requestPlugin('cancel_task', { task_id: activeTaskId }, function (data) {
                if (data && data.status) {
                    stopPolling();
                    setStatusBadge('CANCELLED', 'rgba(239,68,68,0.15)', '#ef4444');
                    cancelBtn.style.display = 'none';
                    closePanelBtn.style.display = '';
                }
            });
        });

        closePanelBtn.addEventListener('click', function () {
            transferPanel.style.display = 'none';
            form.style.display = '';
            activeTaskId = null;
        });

        historyBtn.addEventListener('click', function () {
            requestPlugin('get_history', {}, function (data) {
                var list = data || [];
                if (!Array.isArray(list)) list = [];
                if (resolvedLocalDir) {
                    list = list.filter(function (item) { return item.local_dir === resolvedLocalDir; });
                }

                var ov = openOverlay(theme, 'Transfer History' + (siteName ? ' -- ' + siteName : ''));
                if (!list.length) {
                    ov.body.innerHTML = '<p style="opacity:0.6;font-size:13px;">No migrations recorded for this website yet.</p>';
                    return;
                }

                var html = '<table style="width:100%;border-collapse:collapse;font-size:12.5px;">' +
                    '<thead><tr style="text-align:left;opacity:0.6;">' +
                    '<th style="padding:6px 4px;">Host</th><th style="padding:6px 4px;">Remote Dir</th>' +
                    '<th style="padding:6px 4px;">Status</th><th style="padding:6px 4px;">Started</th><th></th>' +
                    '</tr></thead><tbody>';
                list.forEach(function (item) {
                    var started = new Date(item.started_at * 1000).toLocaleString();
                    var statusColor = item.status === 'success' ? '#10b981' : (item.status === 'running' ? '#f59e0b' : '#ef4444');
                    html += '<tr style="border-top:1px solid ' + theme.borderColor + ';">' +
                        '<td style="padding:6px 4px;font-family:Consolas,Monaco,monospace;">' + item.host + '</td>' +
                        '<td style="padding:6px 4px;">' + item.remote_dir + '</td>' +
                        '<td style="padding:6px 4px;color:' + statusColor + ';font-weight:600;">' + item.status + '</td>' +
                        '<td style="padding:6px 4px;opacity:0.7;">' + started + '</td>' +
                        '<td style="padding:6px 4px;"><button type="button" class="mig-view-log" data-task="' + item.task_id + '" ' +
                        'style="cursor:pointer;font-size:11px;padding:3px 8px;border-radius:4px;border:1px solid ' + theme.borderColor + ';background:transparent;color:' + theme.textColor + ';">Log</button></td>' +
                        '</tr>';
                });
                html += '</tbody></table>';
                ov.body.innerHTML = html;

                ov.body.querySelectorAll('.mig-view-log').forEach(function (btn) {
                    btn.addEventListener('click', function () {
                        var taskId = btn.getAttribute('data-task');
                        requestPlugin('get_task_status', { task_id: taskId }, function (logData) {
                            var logOv = openOverlay(theme, 'Log -- Task #' + taskId);
                            var logs = (logData && logData.logs) || 'No log records found for this task.';
                            logOv.body.innerHTML = '<div style="background:rgba(0,0,0,0.75);color:#fca5a5;border-radius:6px;padding:10px;' +
                                'height:320px;overflow-y:auto;font-family:Consolas,Monaco,monospace;font-size:11.5px;white-space:pre-wrap;">' +
                                logs.replace(/</g, '&lt;') + '</div>';
                        });
                    });
                });
            });
        });

        tabItem.addEventListener('click', activateOurs);

        // Clicking any real tab must restore the native pane and hide ours.
        tabsWrapper.addEventListener('click', function (e) {
            var tabEl = e.target.closest ? e.target.closest('.n-tabs-tab') : null;
            if (tabEl && tabEl.getAttribute('data-name') !== CUSTOM_TAB_NAME) deactivateOurs();
        });
    }

    function scan() {
        var dialogs = document.querySelectorAll('.n-dialog');
        var withTabsModal = 0;
        for (var i = 0; i < dialogs.length; i++) {
            var dialogEl = dialogs[i];
            if (dialogEl.querySelector('.bt-tabs-modal')) {
                withTabsModal++;
                attach(dialogEl);
            }
        }
        if (dialogs.length) {
            dlog('scan(): found', dialogs.length, '.n-dialog element(s),', withTabsModal, 'with .bt-tabs-modal inside');
        }
    }

    if (window.MutationObserver) {
        var observer = new MutationObserver(function () { scan(); });
        observer.observe(document.body, { childList: true, subtree: true });
    } else {
        setInterval(scan, 1000);
    }

    // Also scan once in case a modal is already open when this script loads.
    scan();
})();
