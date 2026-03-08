import { useState } from 'react';
import type { FormEvent } from 'react';

import type { ConnectorPayload } from '../types/api';

type NextcloudConnectorFormProps = {
  onSubmit: (payload: ConnectorPayload) => Promise<void>;
};

const initialForm: ConnectorPayload = {
  display_name: 'Primary Nextcloud',
  base_url: 'https://nextcloud.local',
  username: '',
  secret: '',
  root_path: '/',
  verify_tls: true,
};

export function NextcloudConnectorForm({ onSubmit }: NextcloudConnectorFormProps) {
  const [form, setForm] = useState<ConnectorPayload>(initialForm);
  const [showSecret, setShowSecret] = useState(false);

  const updateField = (key: keyof ConnectorPayload, value: string | boolean) => {
    setForm((current) => ({ ...current, [key]: value }));
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    await onSubmit(form);
    setForm((current) => ({ ...current, secret: '' }));
    setShowSecret(false);
  };

  const passwordToggleLabel = showSecret ? 'Hide app password' : 'Show app password';

  return (
    <form className="card form-card" onSubmit={handleSubmit}>
      <header className="panel-header">
        <h3>New Nextcloud Connector</h3>
      </header>
      <label>
        <span>Name</span>
        <input value={form.display_name} onChange={(event) => updateField('display_name', event.target.value)} />
      </label>
      <label>
        <span>Base URL</span>
        <input value={form.base_url} onChange={(event) => updateField('base_url', event.target.value)} />
      </label>
      <label>
        <span>Username</span>
        <input value={form.username} onChange={(event) => updateField('username', event.target.value)} />
      </label>
      <label>
        <span>App Password</span>
        <div className="input-with-action">
          <input
            type={showSecret ? 'text' : 'password'}
            value={form.secret}
            onChange={(event) => updateField('secret', event.target.value)}
          />
          <button
            type="button"
            className="input-action-button"
            aria-label={passwordToggleLabel}
            title={passwordToggleLabel}
            onClick={() => setShowSecret((current) => !current)}
          >
            {showSecret ? (
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path
                  d="M4 5.4 5.4 4 20 18.6 18.6 20l-2.4-2.4a12.8 12.8 0 0 1-4.2.7C6.7 18.3 2.5 12 2.3 11.7L2 11.2l.3-.5c.1-.2 2.2-3.5 5.8-5.1L4 5.4zm6 6L8.3 9.7A4 4 0 0 0 8 11.2a4 4 0 0 0 5.7 3.6L12 13.1a2 2 0 0 1-2-1.7zm2-5.7c5.3 0 9.5 6.3 9.7 6.6l.3.5-.3.5a16.9 16.9 0 0 1-3.9 4.2l-1.4-1.4a16.1 16.1 0 0 0 3.2-3.1 18.1 18.1 0 0 0-2.1-2.5A11.2 11.2 0 0 0 12 5.7c-.8 0-1.6.1-2.3.3L8 4.3a12.8 12.8 0 0 1 4-.6zm0 2.5a4 4 0 0 1 4 4c0 .5-.1 1.1-.3 1.5l-1.6-1.6a2 2 0 0 0-2.8-2.8L11.7 7.9c.4-.2.9-.3 1.3-.3z"
                  fill="currentColor"
                />
              </svg>
            ) : (
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path
                  d="M12 5.5c5.5 0 9.7 5.9 9.9 6.2l.3.5-.3.5c-.2.3-4.4 6.2-9.9 6.2S2.3 13.1 2.1 12.8l-.3-.5.3-.5c.2-.3 4.4-6.2 9.9-6.2zm0 11.4c3.8 0 7 3.7 8 5a16.6 16.6 0 0 0-2.1-2.5A10.4 10.4 0 0 0 12 7.5c-3.8 0-7 3.7-8 5 1 1.3 4.2 4.4 8 4.4zm0-7.4a2.8 2.8 0 1 1 0 5.6 2.8 2.8 0 0 1 0-5.6zm0 2a.8.8 0 1 0 0 1.6.8.8 0 0 0 0-1.6z"
                  fill="currentColor"
                />
              </svg>
            )}
          </button>
        </div>
      </label>
      <label>
        <span>Root Path</span>
        <input value={form.root_path} onChange={(event) => updateField('root_path', event.target.value)} />
      </label>
      <label className="checkbox-row">
        <input
          type="checkbox"
          checked={Boolean(form.verify_tls)}
          onChange={(event) => updateField('verify_tls', event.target.checked)}
        />
        <span>Verify TLS</span>
      </label>
      <button type="submit">Save Connector</button>
    </form>
  );
}
