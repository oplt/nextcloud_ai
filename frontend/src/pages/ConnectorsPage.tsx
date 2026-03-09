import type { Connector, ConnectorPayload } from '../types/api';
import { NextcloudConnectorForm } from '../components/NextcloudConnectorForm';
import DeleteOutlineOutlinedIcon from '@mui/icons-material/DeleteOutlineOutlined';

type ConnectorsPageProps = {
  connectors: Connector[];
  onCreate: (payload: ConnectorPayload) => Promise<void>;
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
        <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5">
          <rect x="2" y="3" width="6" height="4" rx="1" />
          <rect x="12" y="3" width="6" height="4" rx="1" />
          <rect x="7" y="13" width="6" height="4" rx="1" />
          <path d="M5 7v2a3 3 0 0 0 3 3h4a3 3 0 0 0 3-3V7" strokeLinecap="round" />
          <line x1="10" y1="12" x2="10" y2="13" strokeLinecap="round" />
        </svg>
      </div>
      <span>No connectors configured yet. Add one using the form.</span>
    </div>
  );
}

// ─── ConnectorsPage ───────────────────────────────────────────
export function ConnectorsPage({
  connectors,
  onCreate,
  onDelete,
  onTest,
  onSync,
  onToggleActive,
}: ConnectorsPageProps) {
  const handleDelete = async (id: string, name: string) => {
    if (!window.confirm(`Delete "${name}" and all its synced documents?`)) return;
    await onDelete(id);
  };

  return (
    <section className="split-layout">
      <NextcloudConnectorForm onSubmit={onCreate} />

      <div className="card table-card">
        <header className="panel-header">
          <h3>Configured Connectors</h3>
          {connectors.length > 0 ? <span>{connectors.length}</span> : null}
        </header>

        {connectors.length === 0 ? (
          <EmptyConnectors />
        ) : (
          <div className="connector-list">
            {connectors.map((connector) => (
              <article key={connector.id} className="connector-card">
                <div className="connector-card__info">
                  <strong>{connector.display_name}</strong>
                  <p title={connector.base_url}>{connector.base_url}</p>
                </div>

                <div className="connector-actions">
                  <span className={`pill pill--${connector.is_active ? 'active' : 'inactive'}`}>
                    {connector.is_active ? 'active' : 'inactive'}
                  </span>
                  <span className={`pill pill--${connector.status}`}>
                    {connector.status}
                  </span>
                  <button
                    type="button"
                    onClick={() => void onToggleActive(connector.id, !connector.is_active)}
                  >
                    {connector.is_active ? 'Deactivate' : 'Activate'}
                  </button>
                  <button type="button" onClick={() => void onTest(connector.id)}>
                    Test
                  </button>
                  <button type="button" onClick={() => void onSync(connector.id, false)}>
                    Sync
                  </button>
                  <button type="button" onClick={() => void onSync(connector.id, true)}>
                    Full reindex
                  </button>
                  <button
                    type="button"
                    className="icon-button icon-button--danger"
                    onClick={() => void handleDelete(connector.id, connector.display_name)}
                    aria-label={`Delete ${connector.display_name}`}
                    title="Delete connector"
                  >
                    <DeleteOutlineOutlinedIcon />
                  </button>
                </div>
              </article>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
