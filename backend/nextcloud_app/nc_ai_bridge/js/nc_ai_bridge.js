(function () {
  'use strict';

  async function bootstrapAndPost() {
    const root = document.getElementById('nc-ai-bridge');
    if (!root) return;

    const statusEl = document.getElementById('nc-ai-bridge-status');
    const bootstrapUrl = root.dataset.bootstrapUrl;
    const ssoConsumeUrl = root.dataset.ssoConsumeUrl;
    const fastapiBaseUrl = root.dataset.fastapiBaseUrl;

    if (!fastapiBaseUrl || !bootstrapUrl || !ssoConsumeUrl) {
      if (statusEl) {
        statusEl.textContent = 'Bridge configuration is incomplete. Set nc_ai_bridge.fastapi_base_url in app config.';
      }
      return;
    }

    try {
      const response = await fetch(bootstrapUrl, {
        method: 'POST',
        headers: {
          'Accept': 'application/json',
          'requesttoken': OC.requestToken,
        },
        credentials: 'same-origin',
      });

      if (!response.ok) {
        const errText = await response.text();
        throw new Error(errText || 'Bootstrap request failed');
      }

      const data = await response.json();
      if (!data.bridge_token) {
        throw new Error('Bootstrap response did not contain bridge_token');
      }

      if (statusEl) {
        statusEl.textContent = 'Signing you in to the AI workspace…';
      }

      const form = document.createElement('form');
      form.method = 'POST';
      form.action = ssoConsumeUrl;
      form.style.display = 'none';

      const tokenInput = document.createElement('input');
      tokenInput.type = 'hidden';
      tokenInput.name = 'bridge_token';
      tokenInput.value = data.bridge_token;
      form.appendChild(tokenInput);

      document.body.appendChild(form);
      form.submit();
    } catch (error) {
      if (statusEl) {
        statusEl.textContent = 'Bridge launch failed: ' + (error && error.message ? error.message : String(error));
      }
      console.error('NC AI Bridge launch failed', error);
    }
  }

  window.addEventListener('DOMContentLoaded', bootstrapAndPost);
})();
