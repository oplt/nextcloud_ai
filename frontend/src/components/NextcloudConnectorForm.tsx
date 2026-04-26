import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import IconButton from '@mui/material/IconButton';
import InputAdornment from '@mui/material/InputAdornment';
import VisibilityOffOutlinedIcon from '@mui/icons-material/VisibilityOffOutlined';
import VisibilityOutlinedIcon from '@mui/icons-material/VisibilityOutlined';

import { AppButton } from './ui/AppButton';
import { AppCard } from './ui/AppCard';
import { AppCheckbox } from './ui/AppCheckbox';
import { AppSelectField } from './ui/AppSelectField';
import { AppTextField } from './ui/AppTextField';
import type { Connector, ConnectorPayload, ConnectorUpdatePayload } from '../types/api';

type NextcloudConnectorFormProps = {
  editingConnector?: Connector | null;
  onSubmit: (payload: ConnectorPayload | ConnectorUpdatePayload) => Promise<void>;
  onCancelEdit?: () => void;
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

function connectorToForm(connector: Connector): ConnectorPayload {
  const metadata = connector.metadata_json ?? {};
  const connectorType = connector.connector_type === 'imap' ? 'imap' : 'nextcloud';
  return {
    connector_type: connectorType,
    display_name: connector.display_name,
    base_url: connector.base_url,
    username: connector.username,
    secret: '',
    root_path: connector.root_path,
    verify_tls: typeof metadata.verify_tls === 'boolean' ? metadata.verify_tls : true,
    port: typeof metadata.port === 'number' ? metadata.port : connectorType === 'imap' ? 993 : undefined,
    use_ssl: typeof metadata.use_ssl === 'boolean' ? metadata.use_ssl : connectorType === 'imap' ? true : undefined,
    search_criteria:
      typeof metadata.search_criteria === 'string' ? metadata.search_criteria : connectorType === 'imap' ? 'ALL' : undefined,
  };
}

function buildUpdatePayload(form: ConnectorPayload): ConnectorUpdatePayload {
  const payload: ConnectorUpdatePayload = {
    display_name: form.display_name.trim(),
    base_url: form.base_url.trim(),
    username: form.username.trim(),
    root_path: form.root_path.trim(),
    verify_tls: Boolean(form.verify_tls),
  };

  if (form.secret.trim()) {
    payload.secret = form.secret;
  }

  if (form.connector_type === 'imap') {
    payload.port = form.port ?? 993;
    payload.use_ssl = Boolean(form.use_ssl);
    payload.search_criteria = (form.search_criteria ?? 'ALL').trim() || 'ALL';
  }

  return payload;
}

export function NextcloudConnectorForm({ editingConnector = null, onSubmit, onCancelEdit }: NextcloudConnectorFormProps) {
  const [form, setForm] = useState<ConnectorPayload>(createInitialForm());
  const [showSecret, setShowSecret] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    setForm(editingConnector ? connectorToForm(editingConnector) : createInitialForm());
    setShowSecret(false);
  }, [editingConnector]);

  const update = (key: keyof ConnectorPayload, value: string | boolean | number | null) => {
    setForm((f) => ({ ...f, [key]: value }));
  };

  const connectorType = form.connector_type ?? 'nextcloud';
  const isImap = connectorType === 'imap';
  const isEditing = editingConnector !== null;

  const isValid =
    form.display_name.trim() &&
    form.base_url.trim() &&
    form.username.trim() &&
    (isEditing || form.secret) &&
    form.root_path.trim();

  const handleSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!isValid) return;
    setSubmitting(true);
    try {
      await onSubmit(
        isEditing
          ? buildUpdatePayload(form)
          : {
              ...form,
              display_name: form.display_name.trim(),
              base_url: form.base_url.trim(),
              username: form.username.trim(),
              root_path: form.root_path.trim(),
              search_criteria: isImap ? (form.search_criteria ?? 'ALL').trim() || 'ALL' : undefined,
            },
      );
      setForm(createInitialForm(connectorType));
      setShowSecret(false);
    } finally {
      setSubmitting(false);
    }
  };

  const eyeLabel = showSecret ? 'Hide secret' : 'Show secret';

  return (
    <form onSubmit={handleSubmit} aria-label={isEditing ? 'Update connector' : 'New connector'}>
      <AppCard className="card form-card">
        <header className="panel-header">
          <h3>{isEditing ? 'Update Connector' : 'New Connector'}</h3>
        </header>

        <div>
        <AppSelectField
          id="connector-type"
          label="Connector Type"
          value={connectorType}
          disabled={isEditing}
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
            placeholder={isImap ? 'imap.example.com or imaps://outlook.office365.com' : 'http://localhost:8081 or https://cloud.example.com'}
            autoComplete="off"
          />
          <small>
            {isImap
              ? 'Use the IMAP host for the shared mailbox. Exchange Online usually exposes `outlook.office365.com` over IMAP.'
              : 'Use the full Nextcloud origin. Docker installs usually look like `http://localhost:8081`.'}
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
            InputProps={{
              endAdornment: (
                <InputAdornment position="end">
                  <IconButton
                    type="button"
                    aria-label={eyeLabel}
                    title={eyeLabel}
                    edge="end"
                    onClick={() => setShowSecret((s) => !s)}
                  >
                    {showSecret ? <VisibilityOffOutlinedIcon fontSize="small" /> : <VisibilityOutlinedIcon fontSize="small" />}
                  </IconButton>
                </InputAdornment>
              ),
            }}
          />
          {isEditing ? (
            <small>Leave blank to keep current secret.</small>
          ) : null}
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

          <div className="form-actions">
            {isEditing ? (
              <AppButton type="button" variant="outlined" onClick={onCancelEdit}>
                Cancel
              </AppButton>
            ) : null}
            <AppButton type="submit" disabled={submitting || !isValid}>
              {submitting ? (isEditing ? 'Updating…' : 'Saving…') : isEditing ? 'Update Connector' : 'Save Connector'}
            </AppButton>
          </div>
        </div>
      </AppCard>
    </form>
  );
}
