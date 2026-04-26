import { useState } from 'react';

import type { Connector, ConnectorPayload, ConnectorUpdatePayload } from '../types/api';
import { NextcloudConnectorForm } from '../components/NextcloudConnectorForm';
import { AppButton } from '../components/ui/AppButton';
import { AppCard } from '../components/ui/AppCard';
import { ConfirmDialog } from '../components/ui/ConfirmDialog';
import DeleteOutlineOutlinedIcon from '@mui/icons-material/DeleteOutlineOutlined';
import EditOutlinedIcon from '@mui/icons-material/EditOutlined';
import HubOutlinedIcon from '@mui/icons-material/HubOutlined';
import Alert from '@mui/material/Alert';
import IconButton from '@mui/material/IconButton';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';

type ConnectorsPageProps = {
  connectors: Connector[];
  listLoading?: boolean;
  listError?: string | null;
  onCreate: (payload: ConnectorPayload) => Promise<void>;
  onUpdate: (connectorId: string, payload: ConnectorUpdatePayload) => Promise<void>;
  onDelete: (connectorId: string) => Promise<void>;
  onTest: (connectorId: string) => Promise<void>;
  onSync: (connectorId: string, fullReindex?: boolean) => Promise<void>;
  onToggleActive: (connectorId: string, nextActive: boolean) => Promise<void>;
};



// ─── Empty state ─────────────────────────────────────────────
function EmptyConnectors() {
  return (
    <div className="empty-state">
      <div className="empty-state-icon" aria-hidden="true">
        <HubOutlinedIcon fontSize="medium" />
      </div>
      <span>No connectors configured yet. Add one using the form.</span>
    </div>
  );
}

// ─── ConnectorsPage ───────────────────────────────────────────
export function ConnectorsPage({
  connectors,
  listLoading = false,
  listError = null,
  onCreate,
  onUpdate,
  onDelete,
  onTest,
  onSync,
  onToggleActive,
}: ConnectorsPageProps) {
  const [deleteTarget, setDeleteTarget] = useState<{ id: string; name: string } | null>(null);
  const [editingConnector, setEditingConnector] = useState<Connector | null>(null);
  const statusTone = (status: string) => (status === 'healthy' ? 'healthy' : 'error');

  return (
    <section className="split-layout">
      <NextcloudConnectorForm
        editingConnector={editingConnector}
        onCancelEdit={() => setEditingConnector(null)}
        onSubmit={(payload) => {
          if (editingConnector) {
            return onUpdate(editingConnector.id, payload as ConnectorUpdatePayload).then(() => {
              setEditingConnector(null);
            });
          }
          return onCreate(payload as ConnectorPayload);
        }}
      />

      <AppCard className="card table-card">
        <header className="panel-header">
          <h3>Configured Connectors</h3>
          {connectors.length > 0 ? <span>{connectors.length}</span> : null}
        </header>

        {listError ? (
          <Alert severity="error" className="page-alert">
            {listError}
          </Alert>
        ) : null}
        {listLoading ? (
          <Alert severity="info" className="page-alert" role="status">
            Loading connector list…
          </Alert>
        ) : null}

        {connectors.length === 0 ? (
          <EmptyConnectors />
        ) : (
          <div className="connector-list">
            {connectors.map((connector) => (
              <article key={connector.id} className="connector-card">
                <div className="connector-card__info">
                  <strong>{connector.display_name}</strong>
                  <p title={connector.base_url}>{connector.base_url}</p>
                  <small>
                    Type: {connector.connector_type === 'imap' ? 'IMAP email' : 'Nextcloud'}
                  </small>
                  <small>
                    Scope: {connector.root_path}
                  </small>
                  <small>
                    Owner: {connector.owner?.full_name || connector.owner?.email || connector.owner?.username || 'Unassigned'}
                  </small>
                </div>

                <Stack className="connector-actions" direction="row" useFlexGap flexWrap="wrap">
                  <span className={`pill pill--${connector.is_active ? 'active' : 'inactive'}`}>
                    {connector.is_active ? 'active' : 'inactive'}
                  </span>
                  <span className={`pill pill--${statusTone(connector.status)}`}>
                    {connector.status}
                  </span>
                  <AppButton
                    type="button"
                    variant="outlined"
                    size="small"
                    onClick={() => void onToggleActive(connector.id, !connector.is_active)}
                  >
                    {connector.is_active ? 'Deactivate' : 'Activate'}
                  </AppButton>
                  <AppButton type="button" variant="outlined" size="small" onClick={() => void onTest(connector.id)}>
                    Test
                  </AppButton>
                  <AppButton type="button" variant="outlined" size="small" onClick={() => void onSync(connector.id, false)}>
                    Sync
                  </AppButton>
                  <AppButton type="button" variant="outlined" size="small" onClick={() => void onSync(connector.id, true)}>
                    Full reindex
                  </AppButton>
                  <IconButton
                    type="button"
                    className="icon-button"
                    onClick={() => setEditingConnector(connector)}
                    aria-label={`Update ${connector.display_name}`}
                    title="Update connector"
                  >
                    <EditOutlinedIcon fontSize="small" />
                  </IconButton>
                  <IconButton
                    type="button"
                    className="icon-button icon-button--danger"
                    onClick={() => setDeleteTarget({ id: connector.id, name: connector.display_name })}
                    aria-label={`Delete ${connector.display_name}`}
                    title="Delete connector"
                    color="error"
                  >
                    <DeleteOutlineOutlinedIcon fontSize="small" />
                  </IconButton>
                </Stack>
              </article>
            ))}
          </div>
        )}
      </AppCard>

      <ConfirmDialog
        open={deleteTarget !== null}
        title="Delete connector?"
        description={
          deleteTarget ? (
            <Typography component="p">
                This removes <strong>{deleteTarget.name}</strong> and all documents synced from that source. Running
                jobs may fail; you can add the connector again later.
            </Typography>
          ) : null
        }
        confirmLabel="Delete connector"
        cancelLabel="Cancel"
        variant="danger"
        onCancel={() => setDeleteTarget(null)}
        onConfirm={() => {
          if (!deleteTarget) return;
          const id = deleteTarget.id;
          setDeleteTarget(null);
          void onDelete(id);
        }}
      />
    </section>
  );
}
