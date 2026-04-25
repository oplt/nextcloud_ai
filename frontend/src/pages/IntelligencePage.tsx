import { useMemo, useState } from 'react';

import CardActionArea from '@mui/material/CardActionArea';

import { AppCard } from '../components/ui/AppCard';
import type {
  Connector,
  DocumentDetail,
  IntelligenceOverview,
  IntelligenceSpotlightDocument,
  WorkflowTask,
} from '../types/api';
import { formatConfidence, formatTaxonomyLabel, getBusinessDomainLabel, getDocumentTypeLabel, formatDateTime } from '../utils/documentDisplay';

type IntelligencePageProps = {
  overview: IntelligenceOverview | null;
  loading: boolean;
  error: string | null;
  connectors: Connector[];
  selectedDocument: DocumentDetail | null;
  onSelectDocument: (documentId: string) => Promise<void>;
};

type TaskFilter = 'all' | 'compliance' | 'contract' | 'meeting' | 'high_priority' | 'due_soon';

const TASK_FILTERS: Array<{ key: TaskFilter; label: string }> = [
  { key: 'all', label: 'All' },
  { key: 'compliance', label: 'Compliance' },
  { key: 'contract', label: 'Contract' },
  { key: 'meeting', label: 'Meeting' },
  { key: 'high_priority', label: 'High priority' },
  { key: 'due_soon', label: 'Due soon' },
];

function formatKey(value: string): string {
  return value.replace(/[_-]+/g, ' ');
}

function spotlightLabel(value: string | null): string {
  if (!value || value === 'general' || value === 'unclassified') return 'Unclassified';
  return formatTaxonomyLabel(value);
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

function taskMatchesNeedle(task: WorkflowTask, needle: string): boolean {
  const haystack = [task.queue_name, task.title, task.description, task.document_file_name]
      .filter(Boolean)
      .join(' ')
      .toLowerCase();
  return haystack.includes(needle);
}

function taskConfidence(task: WorkflowTask): number | null {
  const meta = task.metadata_json;
  if (!meta || typeof meta !== 'object') {
    return null;
  }

  const raw =
      (meta as { confidence?: unknown }).confidence ??
      (meta as { confidence_score?: unknown }).confidence_score;

  if (typeof raw !== 'number' || Number.isNaN(raw)) {
    return null;
  }

  return raw > 1 ? Math.round(raw) : Math.round(raw * 100);
}

function isHighPriority(task: WorkflowTask): boolean {
  const priority = task.priority?.toLowerCase() ?? '';
  return ['urgent', 'high', 'critical'].includes(priority);
}

function isDueSoon(task: WorkflowTask): boolean {
  if (!task.due_at) {
    return false;
  }

  const due = new Date(task.due_at).getTime();
  if (Number.isNaN(due)) {
    return false;
  }

  const now = Date.now();
  const sevenDays = 7 * 24 * 60 * 60 * 1000;
  return due <= now + sevenDays;
}

function filterTasks(tasks: WorkflowTask[], activeFilter: TaskFilter): WorkflowTask[] {
  switch (activeFilter) {
    case 'compliance':
      return tasks.filter((task) => taskMatchesNeedle(task, 'compliance'));
    case 'contract':
      return tasks.filter((task) => taskMatchesNeedle(task, 'contract'));
    case 'meeting':
      return tasks.filter((task) => taskMatchesNeedle(task, 'meeting'));
    case 'high_priority':
      return tasks.filter(isHighPriority);
    case 'due_soon':
      return tasks.filter(isDueSoon);
    case 'all':
    default:
      return tasks;
  }
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
      <AppCard className="card card--row intelligence-spotlight">
        <CardActionArea onClick={() => onSelect(document.document_id)} sx={{ p: 2, borderRadius: 'inherit' }}>
          <div className="intelligence-spotlight__header">
            <span className="eyebrow">{spotlightLabel(document.classification)}</span>
            <span className="pill pill--neutral">{document.open_task_count} tasks</span>
          </div>
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
  const [activeTaskFilter, setActiveTaskFilter] = useState<TaskFilter>('all');

  const visibleOpenTasks = useMemo(
      () => filterTasks(overview?.open_tasks ?? [], activeTaskFilter),
      [overview?.open_tasks, activeTaskFilter],
  );

  const queueHealth = useMemo(() => {
    const openTasks = overview?.open_tasks ?? [];
    return {
      pendingReview: openTasks.length,
      highPriority: openTasks.filter(isHighPriority).length,
      dueSoon: openTasks.filter(isDueSoon).length,
      suggestions: openTasks.filter((task) => taskPresentation(task) === 'suggestion').length,
    };
  }, [overview?.open_tasks]);

  if (error) {
    return (
        <AppCard component="section" className="card card--panel detail-card">
          <div className="page-alert page-alert--error" role="alert">
            {error}
          </div>
        </AppCard>
    );
  }

  if (loading) {
    return (
        <AppCard component="section" className="card card--panel detail-card">
          <div className="page-alert page-alert--info" role="status" aria-live="polite">
            Loading intelligence overview…
          </div>
        </AppCard>
    );
  }

  if (!overview) {
    return (
        <AppCard component="section" className="card card--panel detail-card">
          <div className="empty-state" style={{ minHeight: 260 }}>
            <span>No intelligence data yet. Sync or reindex documents to generate structured outputs.</span>
          </div>
        </AppCard>
    );
  }

  if (overview.intelligence_feature_enabled === false) {
    return (
        <AppCard component="section" className="card card--panel detail-card">
          <div className="page-alert page-alert--info" role="status">
            Product intelligence is disabled for this deployment. Chat and document search are unaffected.
          </div>
        </AppCard>
    );
  }

  const documentTypeStats = Object.entries(overview.document_type_counts)
      .map(([key, count]) => ({
        label: formatKey(key),
        value: count,
        group: 'Document type',
      }))
      .slice(0, 4);

  const queueStats = Object.entries(overview.queue_counts)
      .map(([key, count]) => ({
        label: `${formatKey(key)} queue`,
        value: count,
        group: 'Workflow queue',
      }))
      .slice(0, 3);

  const statEntries = [...documentTypeStats, ...queueStats].slice(0, 6);

  return (
      <div className="intelligence-stack">
        <section className="intelligence-command-bar" aria-label="Intelligence command summary">
          <div>
            <span className="eyebrow">AI workflow cockpit</span>
            <h2>{formatKey(overview.wedge)}</h2>
            <p>
              Review generated contract, meeting, and compliance work items against the indexed source documents before
              assigning or approving action.
            </p>
          </div>

          <div className="intelligence-command-summary" aria-label="Workflow summary">
            <div className="intelligence-command-summary__group">
              <span className="summary-pill summary-pill--review">{queueHealth.pendingReview} pending review</span>
              <span className="summary-pill summary-pill--danger">{queueHealth.highPriority} high priority</span>
              <span className="summary-pill summary-pill--warning">{queueHealth.dueSoon} due soon</span>
              <span className="summary-pill summary-pill--suggestion">{queueHealth.suggestions} suggestions</span>
            </div>

            <div className="intelligence-command-summary__group intelligence-command-summary__group--secondary">
              {statEntries.map((entry) => (
                  <span key={entry.label} className="summary-pill summary-pill--neutral">{entry.value} {entry.label}</span>
              ))}
            </div>
          </div>

        </section>


        <section className="split-layout intelligence-layout">
          <div className="documents-panel">
            <AppCard component="section" className="card card--panel table-card workflow-tasks-card">
              <header className="panel-header workflow-tasks-header">
                <div>
                  <h3>Open workflow tasks</h3>
                  <p className="filter-card__meta">
                    Human-review queue for extracted obligations, compliance gaps, meeting follow-ups, and contract signals.
                  </p>
                </div>
                <span className="panel-header__count">{visibleOpenTasks.length}</span>
              </header>

              <div className="task-filter-tabs" role="tablist" aria-label="Filter workflow tasks">
                {TASK_FILTERS.map((filter) => (
                    <button
                        key={filter.key}
                        type="button"
                        className={filter.key === activeTaskFilter ? 'task-filter-tab task-filter-tab--active' : 'task-filter-tab'}
                        onClick={() => setActiveTaskFilter(filter.key)}
                    >
                      {filter.label}
                    </button>
                ))}
              </div>

              <div className="workflow-tasks-scroll">
                {visibleOpenTasks.length === 0 ? (
                    <div className="empty-state workflow-tasks-empty">
                      <span>No open workflow tasks for this filter.</span>
                    </div>
                ) : (
                    <div className="intelligence-task-list">
                      {visibleOpenTasks.map((task) => {
                        const provLine = formatProvenanceSummary(task.metadata_json);
                        const confidence = taskConfidence(task);

                        return (
                            <AppCard key={task.id} className="card card--row intelligence-task-card">
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
                                    {confidence !== null ? <span className="pill pill--neutral">{confidence}%</span> : null}
                                    <span className={`pill pill--${task.priority}`}>{formatKey(task.priority)}</span>
                            </span>
                                </div>
                                <p>{task.description ?? 'No description provided.'}</p>
                                <small>{renderTaskMeta(task)}</small>
                                {provLine ? <small className="filter-card__meta intelligence-task-card__evidence">{provLine}</small> : null}
                                {task.document_file_name ? <span className="eyebrow">{task.document_file_name}</span> : null}
                                <div className="intelligence-task-card__actions" aria-label="Suggested review actions">
                                  <span>Review source</span>
                                  <span>Assign</span>
                                  <span>Snooze</span>
                                </div>
                              </CardActionArea>
                            </AppCard>
                        );
                      })}
                    </div>
                )}
              </div>
            </AppCard>

            <AppCard component="section" className="card card--panel table-card">
              <header className="panel-header">
                <div>
                  <h3>Spotlight documents</h3>
                  <p className="filter-card__meta">
                    Documents currently driving contract, meeting, compliance, or email workflows.
                  </p>
                </div>
                <span className="panel-header__count">{overview.spotlight_documents.length}</span>
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

          <AppCard component="section" className="card card--panel detail-card intelligence-detail">
            {selectedDocument ? (
                <>
                  <header className="panel-header">
                    <div>
                      <span className="eyebrow">Selected intelligence document</span>
                      <h3>{selectedDocument.file_name}</h3>
                      <p className="detail-focus__path">{selectedDocument.file_path}</p>
                      <div className="detail-focus__badges">
                        <span className="pill">{getDocumentTypeLabel(selectedDocument)}</span>
                        <span className="pill pill--neutral">{getBusinessDomainLabel(selectedDocument)}</span>
                        <span className="pill pill--neutral">
                          {formatConfidence(Math.min(selectedDocument.document_type_confidence, selectedDocument.business_domain_confidence))}
                        </span>
                        {selectedDocument.needs_review ? <span className="pill pill--warning">Needs review</span> : null}
                      </div>
                    </div>
                  </header>

                  <section className="intelligence-section">
                    <h4>Classification evidence</h4>
                    <div className="intelligence-mini-list">
                      <article className="intelligence-mini-card">
                        <strong>{getDocumentTypeLabel(selectedDocument)} / {getBusinessDomainLabel(selectedDocument)}</strong>
                        <small>{selectedDocument.document_type_reason ?? 'No document type evidence recorded.'}</small>
                        <small>{selectedDocument.business_domain_reason ?? 'No domain evidence recorded.'}</small>
                      </article>
                    </div>
                  </section>

                  <section className="intelligence-section">
                    <h4>Extracted signals</h4>
                    <div className="intelligence-node-cloud">
                      {Object.entries(selectedDocument.signal_counts).map(([key, count]) => (
                        <span key={key} className="pill pill--neutral">{count} {formatTaxonomyLabel(key)}</span>
                      ))}
                    </div>
                  </section>

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
                                    <small>
                                      {source?.label ?? 'document'} → {target?.label ?? 'unknown'}
                                    </small>
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
