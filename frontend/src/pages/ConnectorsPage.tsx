import type { Connector, ConnectorPayload } from '../types/api';
import { NextcloudConnectorForm } from '../components/NextcloudConnectorForm';

type ConnectorsPageProps = {
  connectors: Connector[];
  onCreate: (payload: ConnectorPayload) => Promise<void>;
  onDelete: (connectorId: string) => Promise<void>;
  onTest: (connectorId: string) => Promise<unknown>;
  onSync: (connectorId: string, fullReindex?: boolean) => Promise<unknown>;
};

// ─── Icons ────────────────────────────────────────────────────
function TrashIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <polyline points="3 5 5 5 17 5" />
      <path d="M16 5l-.9 11a1 1 0 0 1-1 .9H5.9a1 1 0 0 1-1-.9L4 5" />
      <path d="M8 9v5M12 9v5" />
      <path d="M7.5 5V3.5A.5.5 0 0 1 8 3h4a.5.5 0 0 1 .5.5V5" />
    </svg>
  );
}

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
                  <span className={`pill pill--${connector.status}`}>
                    {connector.status}
                  </span>
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
                    <TrashIcon />
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
