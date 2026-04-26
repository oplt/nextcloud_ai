import { useState } from 'react';

import { getDocumentOriginalUrl, updateDocumentClassification } from '../api/client';
import DescriptionOutlinedIcon from '@mui/icons-material/DescriptionOutlined';
import Alert from '@mui/material/Alert';

import { AppButton } from './ui/AppButton';
import { AppCard } from './ui/AppCard';
import type { DocumentDetail } from '../types/api';
import {
  formatConfidence,
  formatDateTime,
  formatFileSize,
  formatTaxonomyLabel,
  getBusinessDomainLabel,
  getDocumentTypeLabel,
} from '../utils/documentDisplay';

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
  const [manualType, setManualType] = useState('');
  const [manualDomain, setManualDomain] = useState('');
  const [manualStatus, setManualStatus] = useState<string | null>(null);
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
            <span className="pill pill--neutral">{getBusinessDomainLabel(document)}</span>
            {document.needs_review ? <span className="pill pill--warning">Needs review</span> : null}
            <span className={`pill pill--${document.parse_status}`}>{document.parse_status}</span>
          </div>
        </div>

        <dl className="detail-focus__grid">
          <div><dt>Document type</dt><dd>{getDocumentTypeLabel(document)} ({formatConfidence(document.document_type_confidence)})</dd></div>
          <div><dt>Business domain</dt><dd>{getBusinessDomainLabel(document)} ({formatConfidence(document.business_domain_confidence)})</dd></div>
          <div><dt>Classification source</dt><dd>{document.document_type_source} / {document.business_domain_source}</dd></div>
          <div><dt>Mime type</dt><dd>{document.mime_type ?? 'Unknown'}</dd></div>
          <div><dt>Modified</dt><dd>{formatDateTime(document.modified_at)}</dd></div>
          <div><dt>Indexed</dt><dd>{formatDateTime(document.indexed_at)}</dd></div>
          <div><dt>Size</dt><dd>{formatFileSize(document.size_bytes)}</dd></div>
          <div><dt>Owner</dt><dd>{document.owner_external_id ?? 'Unknown'}</dd></div>
          <div><dt>Checksum</dt><dd>{document.checksum?.slice(0, 16) ?? 'Unknown'}</dd></div>
          <div><dt>Chunks</dt><dd>{document.chunk_count}</dd></div>
        </dl>

        <div className="intelligence-mini-list" style={{ marginTop: 12 }}>
          <article className="intelligence-mini-card">
            <strong>Classification evidence</strong>
            <small>{document.document_type_reason ?? 'No document type reason recorded.'}</small>
            <small>{document.business_domain_reason ?? 'No business domain reason recorded.'}</small>
          </article>
        </div>

        {document.parse_error ? (
          <Alert severity="error" className="error-banner" sx={{ mt: 1.5 }}>{document.parse_error}</Alert>
        ) : null}
      </section>

      <section className="intelligence-section">
        <h4>Extracted signals</h4>
        <div className="intelligence-node-cloud">
          {Object.entries(document.signal_counts).map(([key, count]) => (
            <span key={key} className="pill pill--neutral">{count} {formatTaxonomyLabel(key)}</span>
          ))}
        </div>
        <pre className="code-block">{JSON.stringify(document.intelligence_json ?? {}, null, 2)}</pre>
      </section>

      <section className="intelligence-section">
        <h4>Chunk preview</h4>
        {document.chunks.slice(0, 5).map((chunk) => (
          <article key={chunk.id} className="intelligence-mini-card">
            <strong>
              #{chunk.chunk_index} {chunk.section_title ?? chunk.chunk_type}
            </strong>
            <small>
              {chunk.embedding_status} {chunk.page_number ? `• page ${chunk.page_number}` : ''} {chunk.heading_path ?? ''}
            </small>
            <p>{chunk.content.slice(0, 360)}</p>
          </article>
        ))}
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
        <h4>Correct category</h4>
        <div className="filter-grid">
          <select value={manualType || document.document_type} onChange={(event) => setManualType(event.target.value)}>
            {['contract', 'invoice_finance', 'legal', 'compliance', 'meeting_notes', 'technical_documentation', 'hr', 'sales_proposal', 'project_document', 'support_operations', 'general_knowledge', 'unclassified'].map((value) => (
              <option key={value} value={value}>{formatTaxonomyLabel(value)}</option>
            ))}
          </select>
          <select value={manualDomain || document.business_domain} onChange={(event) => setManualDomain(event.target.value)}>
            {['legal', 'finance', 'hr', 'engineering', 'operations', 'sales', 'procurement', 'compliance', 'customer_support', 'management', 'unknown'].map((value) => (
              <option key={value} value={value}>{formatTaxonomyLabel(value)}</option>
            ))}
          </select>
          <AppButton
            type="button"
            variant="outlined"
            onClick={async () => {
              await updateDocumentClassification(document.id, {
                document_type: manualType || document.document_type,
                business_domain: manualDomain || document.business_domain,
              });
              setManualStatus('Manual category saved. Reopen document to refresh detail.');
            }}
          >
            Save correction
          </AppButton>
        </div>
        {manualStatus ? <p className="filter-card__meta">{manualStatus}</p> : null}
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
