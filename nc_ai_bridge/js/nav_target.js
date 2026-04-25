(function () {
  'use strict';

  const APP_PATH_FRAGMENT = '/apps/nc_ai_bridge';
  const BRIDGE_LABELS = ['ai workspace', 'nc ai bridge', 'nc_ai_bridge'];

  function inferBridgeHrefFromCurrentLocation() {
    const { origin, pathname } = window.location;
    const indexPhpMarker = '/index.php/';
    const appsMarker = '/apps/';

    if (pathname.includes(indexPhpMarker)) {
      return `${origin}${pathname.split(indexPhpMarker)[0]}${indexPhpMarker.slice(0, -1)}${APP_PATH_FRAGMENT}/`;
    }

    if (pathname.includes(appsMarker)) {
      return `${origin}${pathname.split(appsMarker)[0]}${APP_PATH_FRAGMENT}/`;
    }

    return `${origin}/index.php${APP_PATH_FRAGMENT}/`;
  }

  function looksLikeBridgeLink(anchor) {
    if (!anchor) {
      return false;
    }

    const text = [
      anchor.getAttribute('aria-label'),
      anchor.getAttribute('title'),
      anchor.dataset?.id,
      anchor.textContent,
      anchor.href,
    ]
      .filter(Boolean)
      .join(' ')
      .toLowerCase();

    return BRIDGE_LABELS.some((label) => text.includes(label));
  }

  function normalizeBridgeHref(href, anchor) {
    if (!href) {
      return href;
    }

    try {
      const parsed = new URL(href, window.location.href);
      if (!parsed.pathname.includes(APP_PATH_FRAGMENT)) {
        if (parsed.origin !== window.location.origin && looksLikeBridgeLink(anchor)) {
          return inferBridgeHrefFromCurrentLocation();
        }
        return parsed.toString();
      }

      if (parsed.origin !== window.location.origin) {
        parsed.protocol = window.location.protocol;
        parsed.host = window.location.host;
      }

      return parsed.toString();
    } catch {
      return href;
    }
  }

  function isPlainLeftClick(event) {
    return event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey;
  }

  function wireLink(anchor) {
    if (!anchor || anchor.dataset.ncAiBridgeWired === '1') {
      return;
    }

    const normalizedHref = normalizeBridgeHref(anchor.getAttribute('href') || anchor.href, anchor);
    if (normalizedHref) {
      anchor.href = normalizedHref;
    }

    anchor.dataset.ncAiBridgeWired = '1';
    anchor.target = '_blank';
    anchor.rel = 'noopener noreferrer';

    anchor.addEventListener('click', (event) => {
      if (!isPlainLeftClick(event)) {
        return;
      }

      event.preventDefault();
      window.open(normalizeBridgeHref(anchor.href, anchor), '_blank', 'noopener,noreferrer');
    });
  }

  function syncNavigationTargets(root) {
    const scope = root instanceof Element || root instanceof Document ? root : document;
    const links = scope.querySelectorAll('a[href], a[aria-label], a[title], a[data-id]');
    links.forEach((anchor) => {
      if (looksLikeBridgeLink(anchor) || (anchor.href && anchor.href.includes(APP_PATH_FRAGMENT))) {
        wireLink(anchor);
      }
    });
  }

  const observer = new MutationObserver((mutations) => {
    for (const mutation of mutations) {
      mutation.addedNodes.forEach((node) => {
        if (!(node instanceof Element)) {
          return;
        }
        if (node.matches(`a[href*="${APP_PATH_FRAGMENT}"]`)) {
          wireLink(node);
        }
        syncNavigationTargets(node);
      });
    }
  });

  window.addEventListener('DOMContentLoaded', () => {
    syncNavigationTargets(document);
    observer.observe(document.body, { childList: true, subtree: true });
  });
})();
