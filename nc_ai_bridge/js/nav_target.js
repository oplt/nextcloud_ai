(function () {
  'use strict';

  const APP_PATH_FRAGMENT = '/apps/nc_ai_bridge';

  function isPlainLeftClick(event) {
    return event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey;
  }

  function wireLink(anchor) {
    if (!anchor || anchor.dataset.ncAiBridgeWired === '1') {
      return;
    }

    anchor.dataset.ncAiBridgeWired = '1';
    anchor.target = '_blank';
    anchor.rel = 'noopener noreferrer';

    anchor.addEventListener('click', (event) => {
      if (!isPlainLeftClick(event)) {
        return;
      }

      event.preventDefault();
      window.open(anchor.href, '_blank', 'noopener,noreferrer');
    });
  }

  function syncNavigationTargets(root) {
    const scope = root instanceof Element || root instanceof Document ? root : document;
    const links = scope.querySelectorAll(`a[href*="${APP_PATH_FRAGMENT}"]`);
    links.forEach(wireLink);
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
