import { getDocumentOriginalUrl } from '../api/client';
import DescriptionOutlinedIcon from '@mui/icons-material/DescriptionOutlined';
import { AppButton } from './ui/AppButton';
import { AppCard } from './ui/AppCard';
import type { DocumentDetail } from '../types/api';
import { formatDateTime, formatFileSize, getDocumentTypeLabel } from '../utils/documentDisplay';

type DocumentViewerProps = {
  document: DocumentDetail | null;
  onReindex?: (documentId: string) => Promise<void>;
};

function EmptyState() {
  return (
    <AppCard className="card detail-card">
      <div className="empty-state" style={{ minHeight: 240 }}>
        <div className="empty-state-icon" aria-hidden="true">
          <DescriptionOutlinedIcon fontSize="medium" />
        </div>
        <span>Select a document to view its details.</span>
      </div>
    </AppCard>
  );
}

export function DocumentViewer({ document, onReindex }: DocumentViewerProps) {
  if (!document) return <EmptyState />;
  const originalUrl = getDocumentOriginalUrl(document.id);
  const isEmailDocument = document.mime_type === 'message/rfc822';

  return (
    <AppCard className="card detail-card">
      <header className="panel-header">
        <div className="detail-card__title-row">
          <h3 className="detail-card__title">{document.file_name}</h3>
          <p className="detail-card__path">{document.file_path}</p>
        </div>
        {onReindex ? (
          <AppButton
            type="button"
            variant="outlined"
            onClick={() => void onReindex(document.id)}
          >
            Reindex
          </AppButton>
        ) : null}
      </header>

      <section className="detail-focus">
        <div className="detail-focus__header">
          <div>
            <span className="eyebrow">Selected document</span>
            <h4 className="detail-focus__title">{document.file_name}</h4>
            <p className="detail-focus__path">{document.file_path}</p>
          </div>
          <div className="detail-focus__badges">
            <span className="pill">{getDocumentTypeLabel(document)}</span>
            <span className={`pill pill--${document.parse_status}`}>{document.parse_status}</span>
          </div>
        </div>

        <dl className="detail-focus__grid">
          <div><dt>Type</dt><dd>{getDocumentTypeLabel(document)}</dd></div>
          <div><dt>Mime type</dt><dd>{document.mime_type ?? 'Unknown'}</dd></div>
          <div><dt>Modified</dt><dd>{formatDateTime(document.modified_at)}</dd></div>
          <div><dt>Indexed</dt><dd>{formatDateTime(document.indexed_at)}</dd></div>
          <div><dt>Size</dt><dd>{formatFileSize(document.size_bytes)}</dd></div>
          <div><dt>Owner</dt><dd>{document.owner_external_id ?? 'Unknown'}</dd></div>
        </dl>

        {document.parse_error ? (
          <p className="error-banner" style={{ marginTop: 12 }}>{document.parse_error}</p>
        ) : null}
      </section>

      <dl className="meta-grid">
        <div><dt>Parse status</dt><dd>{document.parse_status}</dd></div>
        <div><dt>Sync status</dt><dd>{document.sync_status}</dd></div>
        <div>
          <dt>Visible users</dt>
          <dd>{document.allowed_user_ids.join(', ') || 'None'}</dd>
        </div>
        <div>
          <dt>Visible groups</dt>
          <dd>{document.allowed_group_ids.join(', ') || 'None'}</dd>
        </div>
      </dl>

      <section className="document-preview">
        <div className="document-preview__header">
          <div>
            <h4>Original Preview</h4>
            <p>
              {isEmailDocument
                ? 'Rendered from the stored email payload or synced original.'
                : 'Previewed directly from the source connector.'}
            </p>
          </div>
          <a href={originalUrl} target="_blank" rel="noreferrer">
            Open original ↗
          </a>
        </div>

        <iframe
          key={document.id}
          className="document-preview__frame"
          src={originalUrl}
          title={`Preview of ${document.file_name}`}
          loading="lazy"
        />
      </section>

      <section className="intelligence-section">
        <h4>Structured insights</h4>
        {document.insights.length === 0 ? (
          <p className="filter-card__meta">No structured insights generated for this document yet.</p>
        ) : (
          <div className="intelligence-insight-list">
            {document.insights.map((insight) => (
              <article key={insight.id} className="intelligence-insight-card">
                <div className="intelligence-insight-card__header">
                  <strong>{insight.title ?? insight.insight_type}</strong>
                  {insight.confidence ? <span>{Math.round(insight.confidence * 100)}%</span> : null}
                </div>
                <p>{insight.summary ?? 'No summary available.'}</p>
              </article>
            ))}
          </div>
        )}
      </section>

      <section className="intelligence-section">
        <h4>Workflow tasks</h4>
        {document.workflow_tasks.length === 0 ? (
          <p className="filter-card__meta">No workflow tasks generated for this document.</p>
        ) : (
          <div className="intelligence-mini-list">
            {document.workflow_tasks.map((task) => (
              <article key={task.id} className="intelligence-mini-card">
                <strong>{task.title}</strong>
                <small>
                  {task.queue_name} • {task.status} • {task.priority}
                  {task.owner_label ? ` • ${task.owner_label}` : ''}
                </small>
              </article>
            ))}
          </div>
        )}
      </section>

      <section className="intelligence-section">
        <h4>Knowledge links</h4>
        {document.knowledge_nodes.length === 0 ? (
          <p className="filter-card__meta">No graph relationships generated.</p>
        ) : (
          <>
            <div className="intelligence-node-cloud">
              {document.knowledge_nodes
                .filter((node) => node.node_type !== 'document')
                .map((node) => (
                  <span key={node.id} className={`pill pill--graph-${node.node_type}`}>
                    {node.label}
                  </span>
                ))}
            </div>
            <div className="intelligence-mini-list">
              {document.knowledge_edges.map((edge) => {
                const source = document.knowledge_nodes.find((node) => node.id === edge.source_node_id);
                const target = document.knowledge_nodes.find((node) => node.id === edge.target_node_id);
                return (
                  <article key={edge.id} className="intelligence-mini-card">
                    <strong>{edge.relation_type.replace(/[_-]+/g, ' ')}</strong>
                    <small>{source?.label ?? 'document'} → {target?.label ?? 'unknown'}</small>
                  </article>
                );
              })}
            </div>
          </>
        )}
      </section>
    </AppCard>
  );
}
