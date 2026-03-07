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

  const updateField = (key: keyof ConnectorPayload, value: string | boolean) => {
    setForm((current) => ({ ...current, [key]: value }));
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    await onSubmit(form);
    setForm((current) => ({ ...current, secret: '' }));
  };

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
        <input type="password" value={form.secret} onChange={(event) => updateField('secret', event.target.value)} />
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
