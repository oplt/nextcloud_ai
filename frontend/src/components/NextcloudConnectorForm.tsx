import { useState } from 'react';
import type { FormEvent } from 'react';
import type { ConnectorPayload } from '../types/api';

type NextcloudConnectorFormProps = {
  onSubmit: (payload: ConnectorPayload) => Promise<void>;
};

const INITIAL: ConnectorPayload = {
  display_name: 'Primary Nextcloud',
  base_url:     'https://nextcloud.local',
  username:     '',
  secret:       '',
  root_path:    '/',
  verify_tls:   true,
};

function EyeOpenIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
      <path d="M1.5 10S4.5 4 10 4s8.5 6 8.5 6-3 6-8.5 6S1.5 10 1.5 10z" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="10" cy="10" r="2.5" strokeLinecap="round" />
    </svg>
  );
}

function EyeClosedIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
      <path d="M14.5 14.5A9 9 0 0 1 10 16c-5.5 0-8.5-6-8.5-6a15 15 0 0 1 4.1-4.8M7.5 4.2A9 9 0 0 1 10 4c5.5 0 8.5 6 8.5 6a15 15 0 0 1-1.8 2.6M3 3l14 14" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function NextcloudConnectorForm({ onSubmit }: NextcloudConnectorFormProps) {
  const [form, setForm]           = useState<ConnectorPayload>(INITIAL);
  const [showSecret, setShowSecret] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const update = (key: keyof ConnectorPayload, value: string | boolean) => {
    setForm((f) => ({ ...f, [key]: value }));
  };

  const isValid =
    form.display_name.trim() &&
    form.base_url.trim() &&
    form.username.trim() &&
    form.secret;

  const handleSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!isValid) return;
    setSubmitting(true);
    try {
      await onSubmit(form);
      setForm((f) => ({ ...f, secret: '' }));
      setShowSecret(false);
    } finally {
      setSubmitting(false);
    }
  };

  const eyeLabel = showSecret ? 'Hide app password' : 'Show app password';

  return (
    <form className="card form-card" onSubmit={handleSubmit} aria-label="New Nextcloud connector">
      <header className="panel-header">
        <h3>New Nextcloud Connector</h3>
      </header>

      <div>
        <label htmlFor="nc-display-name">
          <span>Display Name</span>
          <input
            id="nc-display-name"
            value={form.display_name}
            onChange={(e) => update('display_name', e.target.value)}
            placeholder="My Nextcloud"
            autoComplete="off"
          />
        </label>

        <label htmlFor="nc-base-url">
          <span>Base URL</span>
          <input
            id="nc-base-url"
            type="url"
            value={form.base_url}
            onChange={(e) => update('base_url', e.target.value)}
            placeholder="https://nextcloud.example.com"
            autoComplete="off"
          />
        </label>

        <label htmlFor="nc-username">
          <span>Username</span>
          <input
            id="nc-username"
            value={form.username}
            onChange={(e) => update('username', e.target.value)}
            placeholder="admin"
            autoComplete="username"
          />
        </label>

        <label htmlFor="nc-secret">
          <span>App Password</span>
          <div className="input-with-action">
            <input
              id="nc-secret"
              type={showSecret ? 'text' : 'password'}
              value={form.secret}
              onChange={(e) => update('secret', e.target.value)}
              placeholder="xxxx-xxxx-xxxx-xxxx"
              autoComplete="current-password"
            />
            <button
              type="button"
              className="input-action-button"
              aria-label={eyeLabel}
              title={eyeLabel}
              onClick={() => setShowSecret((s) => !s)}
            >
              {showSecret ? <EyeClosedIcon /> : <EyeOpenIcon />}
            </button>
          </div>
        </label>

        <label htmlFor="nc-root-path">
          <span>Root Path</span>
          <input
            id="nc-root-path"
            value={form.root_path}
            onChange={(e) => update('root_path', e.target.value)}
            placeholder="/"
          />
        </label>

        <label className="checkbox-row" htmlFor="nc-verify-tls">
          <input
            id="nc-verify-tls"
            type="checkbox"
            checked={Boolean(form.verify_tls)}
            onChange={(e) => update('verify_tls', e.target.checked)}
          />
          <span>Verify TLS certificate</span>
        </label>

        <button type="submit" disabled={submitting || !isValid}>
          {submitting ? 'Saving…' : 'Save Connector'}
        </button>
      </div>
    </form>
  );
}
