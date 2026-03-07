import type { Connector, ConnectorPayload } from '../types/api';
import { NextcloudConnectorForm } from '../components/NextcloudConnectorForm';

type ConnectorsPageProps = {
  connectors: Connector[];
  onCreate: (payload: ConnectorPayload) => Promise<void>;
  onTest: (connectorId: string) => Promise<void>;
  onSync: (connectorId: string, fullReindex?: boolean) => Promise<void>;
};

export function ConnectorsPage({ connectors, onCreate, onTest, onSync }: ConnectorsPageProps) {
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
              </div>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
