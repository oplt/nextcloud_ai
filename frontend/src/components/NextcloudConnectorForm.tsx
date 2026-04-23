import { useState } from 'react';
import type { FormEvent } from 'react';
import IconButton from '@mui/material/IconButton';
import VisibilityOffOutlinedIcon from '@mui/icons-material/VisibilityOffOutlined';
import VisibilityOutlinedIcon from '@mui/icons-material/VisibilityOutlined';

import { AppButton } from './ui/AppButton';
import { AppCard } from './ui/AppCard';
import { AppCheckbox } from './ui/AppCheckbox';
import { AppSelectField } from './ui/AppSelectField';
import { AppTextField } from './ui/AppTextField';
import type { ConnectorPayload } from '../types/api';

type NextcloudConnectorFormProps = {
  onSubmit: (payload: ConnectorPayload) => Promise<void>;
};

function createInitialForm(connectorType: 'nextcloud' | 'imap' = 'nextcloud'): ConnectorPayload {
  if (connectorType === 'imap') {
    return {
      connector_type: 'imap',
      display_name: 'Shared Mailbox',
      base_url: '',
      username: '',
      secret: '',
      root_path: 'INBOX',
      verify_tls: true,
      use_ssl: true,
      port: 993,
      search_criteria: 'ALL',
    };
  }
  return {
    connector_type: 'nextcloud',
    display_name: 'Primary Nextcloud',
    base_url: '',
    username: '',
    secret: '',
    root_path: '/',
    verify_tls: true,
  };
}

export function NextcloudConnectorForm({ onSubmit }: NextcloudConnectorFormProps) {
  const [form, setForm]           = useState<ConnectorPayload>(createInitialForm());
  const [showSecret, setShowSecret] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const update = (key: keyof ConnectorPayload, value: string | boolean | number | null) => {
    setForm((f) => ({ ...f, [key]: value }));
  };

  const connectorType = form.connector_type ?? 'nextcloud';
  const isImap = connectorType === 'imap';

  const isValid =
    form.display_name.trim() &&
    form.base_url.trim() &&
    form.username.trim() &&
    form.secret &&
    form.root_path.trim();

  const handleSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!isValid) return;
    setSubmitting(true);
    try {
      await onSubmit(form);
      setForm((f) => ({ ...createInitialForm(connectorType), ...f, secret: '' }));
      setShowSecret(false);
    } finally {
      setSubmitting(false);
    }
  };

  const eyeLabel = showSecret ? 'Hide secret' : 'Show secret';

  return (
    <form onSubmit={handleSubmit} aria-label="New connector">
      <AppCard className="card form-card">
        <header className="panel-header">
          <h3>New Connector</h3>
        </header>

        <div>
        <AppSelectField
          id="connector-type"
          label="Connector Type"
          value={connectorType}
          onChange={(event) => {
            const nextType = event.target.value as 'nextcloud' | 'imap';
            setForm(createInitialForm(nextType));
          }}
          options={[
            { label: 'Nextcloud files', value: 'nextcloud' },
            { label: 'IMAP email / Exchange inbox', value: 'imap' },
          ]}
        />

        <AppTextField
          id="nc-display-name"
          label="Display Name"
          value={form.display_name}
          onChange={(e) => update('display_name', e.target.value)}
          placeholder="My Nextcloud"
          autoComplete="off"
        />

        <label htmlFor="nc-base-url">
          <AppTextField
            id="nc-base-url"
            type={isImap ? 'text' : 'url'}
            label={isImap ? 'IMAP Host' : 'Base URL'}
            value={form.base_url}
            onChange={(e) => update('base_url', e.target.value)}
            placeholder={isImap ? 'imap.example.com or imaps://outlook.office365.com' : 'http://localhost or https://cloud.example.com'}
            autoComplete="off"
          />
          <small>
            {isImap
              ? 'Use the IMAP host for the shared mailbox. Exchange Online usually exposes `outlook.office365.com` over IMAP.'
              : 'Use the full Nextcloud origin. Local HTTP installs usually look like `http://localhost`.'}
          </small>
        </label>

        <AppTextField
          id="nc-username"
          label={isImap ? 'Mailbox Login' : 'Username'}
          value={form.username}
          onChange={(e) => update('username', e.target.value)}
          placeholder={isImap ? 'shared-mailbox@example.com' : 'admin'}
          autoComplete="username"
        />

        <label htmlFor="nc-secret">
          <AppTextField
            id="nc-secret"
            type={showSecret ? 'text' : 'password'}
            label={isImap ? 'Mailbox Secret' : 'App Password'}
            value={form.secret}
            onChange={(e) => update('secret', e.target.value)}
            placeholder={isImap ? 'mailbox password or app password' : 'xxxx-xxxx-xxxx-xxxx'}
            autoComplete="current-password"
          />
          <div className="input-with-action">
            <IconButton
              type="button"
              className="input-action-button"
              aria-label={eyeLabel}
              title={eyeLabel}
              onClick={() => setShowSecret((s) => !s)}
            >
              {showSecret ? <VisibilityOffOutlinedIcon fontSize="small" /> : <VisibilityOutlinedIcon fontSize="small" />}
            </IconButton>
          </div>
        </label>

        <AppTextField
          id="nc-root-path"
          label={isImap ? 'Mailbox' : 'Root Path'}
          value={form.root_path}
          onChange={(e) => update('root_path', e.target.value)}
          placeholder={isImap ? 'INBOX' : '/'}
        />

        {isImap ? (
          <>
            <AppTextField
              id="imap-port"
              type="number"
              label="Port"
              value={String(form.port ?? 993)}
              onChange={(e) => update('port', Number(e.target.value))}
              inputProps={{ min: 1, max: 65535 }}
            />

            <label htmlFor="imap-search">
              <AppTextField
                id="imap-search"
                label="Search Criteria"
                value={form.search_criteria ?? 'ALL'}
                onChange={(e) => update('search_criteria', e.target.value)}
                placeholder="ALL"
              />
              <small>Examples: `ALL`, `UNSEEN`, `SINCE 1-Apr-2026`.</small>
            </label>

            <label className="checkbox-row" htmlFor="imap-use-ssl">
              <AppCheckbox
                id="imap-use-ssl"
                checked={Boolean(form.use_ssl)}
                onChange={(e) => update('use_ssl', e.target.checked)}
              />
              <span>Use SSL/TLS</span>
            </label>
          </>
        ) : null}

        <label className="checkbox-row" htmlFor="nc-verify-tls">
          <AppCheckbox
            id="nc-verify-tls"
            checked={Boolean(form.verify_tls)}
            onChange={(e) => update('verify_tls', e.target.checked)}
          />
          <span>Verify TLS certificate</span>
        </label>

          <AppButton type="submit" disabled={submitting || !isValid}>
            {submitting ? 'Saving…' : 'Save Connector'}
          </AppButton>
        </div>
      </AppCard>
    </form>
  );
}
