import CardActionArea from '@mui/material/CardActionArea';

import { AppCard } from '../components/ui/AppCard';
import type {
  Connector,
  DocumentDetail,
  IntelligenceOverview,
  IntelligenceSpotlightDocument,
  WorkflowTask,
} from '../types/api';
import { formatDateTime } from '../utils/documentDisplay';

type IntelligencePageProps = {
  overview: IntelligenceOverview | null;
  loading: boolean;
  error: string | null;
  connectors: Connector[];
  selectedDocument: DocumentDetail | null;
  onSelectDocument: (documentId: string) => Promise<void>;
};

function formatKey(value: string): string {
  return value.replace(/[_-]+/g, ' ');
}

function getConnectorLabel(connectors: Connector[], connectorId: string): string {
  return connectors.find((connector) => connector.id === connectorId)?.display_name ?? 'Unknown connector';
}

function renderTaskMeta(task: WorkflowTask) {
  const bits = [
    task.queue_name,
    task.priority,
    task.owner_label,
    task.due_at ? `due ${formatDateTime(task.due_at)}` : null,
  ].filter(Boolean);
  return bits.join(' • ');
}

type ProvenancePayload = {
  methods?: string[];
  evidence_tier?: string;
  notes?: string;
};

function readProvenance(payload: Record<string, unknown> | null | undefined): ProvenancePayload | null {
  const raw = payload?.provenance;
  if (!raw || typeof raw !== 'object') {
    return null;
  }
  return raw as ProvenancePayload;
}

function formatProvenanceSummary(payload: Record<string, unknown> | null | undefined): string | null {
  const p = readProvenance(payload);
  if (!p?.evidence_tier) {
    return null;
  }
  const tier = formatKey(p.evidence_tier);
  const methods = (p.methods ?? []).slice(0, 4).map((m) => formatKey(m));
  const tail = methods.length ? ` · ${methods.join(', ')}${(p.methods?.length ?? 0) > 4 ? '…' : ''}` : '';
  return `Evidence: ${tier}${tail}`;
}

function taskPresentation(task: WorkflowTask): string | null {
  const meta = task.metadata_json;
  if (!meta || typeof meta !== 'object') {
    return null;
  }
  const p = (meta as { presentation?: string }).presentation;
  return typeof p === 'string' ? p : null;
}

function SpotlightCard({
  document,
  connectors,
  onSelect,
}: {
  document: IntelligenceSpotlightDocument;
  connectors: Connector[];
  onSelect: (documentId: string) => void;
}) {
  return (
    <AppCard className="card intelligence-spotlight">
      <CardActionArea onClick={() => onSelect(document.document_id)} sx={{ p: 2, borderRadius: 'inherit' }}>
        <span className="eyebrow">{document.classification ?? 'general'}</span>
        <h3>{document.file_name}</h3>
        <p>{document.file_path}</p>
        <small>{getConnectorLabel(connectors, document.connector_id)}</small>
        <div className="intelligence-spotlight__meta">
          <span>{document.open_task_count} open tasks</span>
          <span>{document.insight_types.length} insight types</span>
        </div>
      </CardActionArea>
    </AppCard>
  );
}

export function IntelligencePage({
  overview,
  loading,
  error,
  connectors,
  selectedDocument,
  onSelectDocument,
}: IntelligencePageProps) {
  if (error) {
    return (
      <AppCard component="section" className="card detail-card">
        <div className="page-alert page-alert--error" role="alert">
          {error}
        </div>
      </AppCard>
    );
  }

  if (loading) {
    return (
      <AppCard component="section" className="card detail-card">
        <div className="page-alert page-alert--info" role="status" aria-live="polite">
          Loading intelligence overview…
        </div>
      </AppCard>
    );
  }

  if (!overview) {
    return (
      <AppCard component="section" className="card detail-card">
        <div className="empty-state" style={{ minHeight: 260 }}>
          <span>No intelligence data yet. Sync or reindex documents to generate structured outputs.</span>
        </div>
      </AppCard>
    );
  }

  if (overview.intelligence_feature_enabled === false) {
    return (
      <AppCard component="section" className="card detail-card">
        <div className="page-alert page-alert--info" role="status">
          Product intelligence is disabled for this deployment. Chat and document search are unaffected.
        </div>
      </AppCard>
    );
  }

  const statEntries = [
    ...Object.entries(overview.document_type_counts).map(([key, count]) => ({
      label: formatKey(key),
      value: count,
    })),
    ...Object.entries(overview.queue_counts).map(([key, count]) => ({
      label: `${formatKey(key)} queue`,
      value: count,
    })),
  ].slice(0, 8);

  return (
    <div className="intelligence-stack">
      <section className="overview-grid intelligence-grid">
        <AppCard className="card hero-card intelligence-hero">
          <span className="eyebrow">Product wedge</span>
          <h2>{formatKey(overview.wedge)}</h2>
          <p>
            Heuristic meeting, contract, and compliance suggestions from indexed text — verify important items in the
            source documents before acting.
          </p>
        </AppCard>
        {statEntries.map((entry) => (
          <AppCard key={entry.label} className="card stat-card">
            <span className="stat-card__label">{entry.label}</span>
            <strong className="stat-card__value">{entry.value}</strong>
          </AppCard>
        ))}
      </section>

      <section className="split-layout intelligence-layout">
        <div className="documents-panel">
          <AppCard component="section" className="card table-card">
            <header className="panel-header">
              <div>
                <h3>Open workflow tasks</h3>
                <p className="filter-card__meta">
                  Tasks from extraction heuristics; compliance items are suggestions until a human reviews them.
                </p>
              </div>
              <span>{overview.open_tasks.length}</span>
            </header>
            {overview.open_tasks.length === 0 ? (
              <div className="empty-state" style={{ minHeight: 180 }}>
                <span>No open workflow tasks.</span>
              </div>
            ) : (
              <div className="intelligence-task-list">
                {overview.open_tasks.map((task) => (
                  <AppCard key={task.id} className="intelligence-task-card">
                    <CardActionArea
                      onClick={() => task.document_id && void onSelectDocument(task.document_id)}
                      sx={{ p: 2, borderRadius: 'inherit' }}
                    >
                      <div className="intelligence-task-card__header">
                        <strong>{task.title}</strong>
                        <span className="intelligence-task-card__pills">
                          {taskPresentation(task) === 'suggestion' ? (
                            <span className="pill pill--suggestion">Suggestion</span>
                          ) : null}
                          <span className={`pill pill--${task.priority}`}>{task.priority}</span>
                        </span>
                      </div>
                      <p>{task.description ?? 'No description provided.'}</p>
                      <small>{renderTaskMeta(task)}</small>
                      {task.document_file_name ? (
                        <span className="eyebrow">{task.document_file_name}</span>
                      ) : null}
                    </CardActionArea>
                  </AppCard>
                ))}
              </div>
            )}
          </AppCard>

          <AppCard component="section" className="card table-card">
            <header className="panel-header">
              <div>
                <h3>Spotlight documents</h3>
                <p className="filter-card__meta">Documents currently driving contract, meeting, compliance, or email workflows.</p>
              </div>
              <span>{overview.spotlight_documents.length}</span>
            </header>
            <div className="intelligence-spotlight-grid">
              {overview.spotlight_documents.map((document) => (
                <SpotlightCard
                  key={document.document_id}
                  document={document}
                  connectors={connectors}
                  onSelect={(documentId) => void onSelectDocument(documentId)}
                />
              ))}
            </div>
          </AppCard>
        </div>

        <AppCard component="section" className="card detail-card intelligence-detail">
          {selectedDocument ? (
            <>
              <header className="panel-header">
                <div>
                  <span className="eyebrow">Selected intelligence document</span>
                  <h3>{selectedDocument.file_name}</h3>
                  <p className="detail-focus__path">{selectedDocument.file_path}</p>
                </div>
              </header>

              <section className="intelligence-section">
                <h4>Insights</h4>
                {selectedDocument.insights.length === 0 ? (
                  <p className="filter-card__meta">No structured insights yet.</p>
                ) : (
                  <div className="intelligence-insight-list">
                    {selectedDocument.insights.map((insight) => {
                      const prov = readProvenance(insight.payload_json);
                      const provLine = formatProvenanceSummary(insight.payload_json);
                      return (
                        <article key={insight.id} className="intelligence-insight-card">
                          <div className="intelligence-insight-card__header">
                            <strong>{insight.title ?? formatKey(insight.insight_type)}</strong>
                            {insight.confidence ? <span>{Math.round(insight.confidence * 100)}%</span> : null}
                          </div>
                          <p>{insight.summary ?? 'No summary available.'}</p>
                          {provLine ? <p className="filter-card__meta">{provLine}</p> : null}
                          {prov?.notes ? (
                            <p className="filter-card__meta" style={{ fontStyle: 'italic' }}>
                              {prov.notes}
                            </p>
                          ) : null}
                        </article>
                      );
                    })}
                  </div>
                )}
              </section>

              <section className="intelligence-section">
                <h4>Workflow tasks</h4>
                {selectedDocument.workflow_tasks.length === 0 ? (
                  <p className="filter-card__meta">No workflow tasks generated.</p>
                ) : (
                  <div className="intelligence-mini-list">
                    {selectedDocument.workflow_tasks.map((task) => (
                      <article key={task.id} className="intelligence-mini-card">
                        <strong>{task.title}</strong>
                        <small>{renderTaskMeta(task)}</small>
                      </article>
                    ))}
                  </div>
                )}
              </section>

              <section className="intelligence-section">
                <h4>Knowledge graph</h4>
                {selectedDocument.knowledge_nodes.length === 0 ? (
                  <p className="filter-card__meta">No graph links generated.</p>
                ) : (
                  <>
                    <div className="intelligence-node-cloud">
                      {selectedDocument.knowledge_nodes
                        .filter((node) => node.node_type !== 'document')
                        .map((node) => (
                          <span key={node.id} className={`pill pill--graph-${node.node_type}`}>
                            {node.label}
                          </span>
                        ))}
                    </div>
                    <div className="intelligence-mini-list">
                      {selectedDocument.knowledge_edges.map((edge) => {
                        const source = selectedDocument.knowledge_nodes.find((node) => node.id === edge.source_node_id);
                        const target = selectedDocument.knowledge_nodes.find((node) => node.id === edge.target_node_id);
                        const edgeProv = formatProvenanceSummary(edge.metadata_json);
                        return (
                          <article key={edge.id} className="intelligence-mini-card">
                            <strong>{formatKey(edge.relation_type)}</strong>
                            <small>{source?.label ?? 'document'} → {target?.label ?? 'unknown'}</small>
                            {edgeProv ? <small className="filter-card__meta">{edgeProv}</small> : null}
                          </article>
                        );
                      })}
                    </div>
                  </>
                )}
              </section>
            </>
          ) : (
            <div className="empty-state" style={{ minHeight: 320 }}>
              <span>Select a spotlight document or workflow task to inspect structured outputs.</span>
            </div>
          )}
        </AppCard>
      </section>
    </div>
  );
}
