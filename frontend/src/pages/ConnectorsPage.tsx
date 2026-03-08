import type { Connector, ConnectorPayload } from '../types/api';
import { NextcloudConnectorForm } from '../components/NextcloudConnectorForm';

type ConnectorsPageProps = {
  connectors: Connector[];
  onCreate: (payload: ConnectorPayload) => Promise<void>;
  onDelete: (connectorId: string) => Promise<void>;
  onTest: (connectorId: string) => Promise<void>;
  onSync: (connectorId: string, fullReindex?: boolean) => Promise<void>;
};

function TrashIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path
        d="M9 3h6l1 2h4v2H4V5h4l1-2zm1 6h2v8h-2V9zm4 0h2v8h-2V9zM7 9h2v8H7V9zm1 11h8a2 2 0 0 0 2-2V8H6v10a2 2 0 0 0 2 2z"
        fill="currentColor"
      />
    </svg>
  );
}

export function ConnectorsPage({ connectors, onCreate, onDelete, onTest, onSync }: ConnectorsPageProps) {
  const handleDelete = async (connectorId: string, displayName: string) => {
    const confirmed = window.confirm(
      `Delete "${displayName}" and all synced documents and jobs for this connector?`
    );
    if (!confirmed) {
      return;
    }
    await onDelete(connectorId);
  };

  return (
    <section className="split-layout">
      <NextcloudConnectorForm onSubmit={onCreate} />
      <div className="card table-card">
        <header className="panel-header">
          <h3>Configured Connectors</h3>
          <span>{connectors.length}</span>
        </header>
        <div className="connector-list">
          {connectors.map((connector) => (
            <article key={connector.id} className="connector-card">
              <div>
                <strong>{connector.display_name}</strong>
                <p>{connector.base_url}</p>
              </div>
              <div className="connector-actions">
                <span className={`pill pill--${connector.status}`}>{connector.status}</span>
                <button type="button" onClick={() => void onTest(connector.id)}>
                  Test
                </button>
                <button type="button" onClick={() => void onSync(connector.id, false)}>
                  Sync
                </button>
                <button type="button" onClick={() => void onSync(connector.id, true)}>
                  Full Reindex
                </button>
                <button
                  type="button"
                  className="icon-button icon-button--danger"
                  onClick={() => void handleDelete(connector.id, connector.display_name)}
                  aria-label={`Delete ${connector.display_name}`}
                  title={`Delete ${connector.display_name}`}
                >
                  <TrashIcon />
                </button>
              </div>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
