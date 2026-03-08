import type { DocumentDetail } from '../types/api';
import { formatDateTime, formatFileSize, getDocumentTypeLabel } from '../utils/documentDisplay';

type DocumentViewerProps = {
  document: DocumentDetail | null;
  onReindex?: (documentId: string) => Promise<void>;
};

export function DocumentViewer({ document, onReindex }: DocumentViewerProps) {
  if (!document) {
    return (
      <div className="card detail-card">
        <p className="empty-state">Select a document row to open its detail view here.</p>
      </div>
    );
  }

  return (
    <div className="card detail-card">
      <header className="panel-header">
        <div>
          <h3>{document.file_name}</h3>
          <p>{document.file_path}</p>
        </div>
        {onReindex ? (
          <button type="button" onClick={() => void onReindex(document.id)}>
            Reindex
          </button>
        ) : null}
      </header>
      <section className="detail-focus">
        <div className="detail-focus__header">
          <div>
            <p className="eyebrow">Selected Document</p>
            <h4>{document.file_name}</h4>
            <p className="detail-focus__path">{document.file_path}</p>
          </div>
          <div className="detail-focus__badges">
            <span className="pill">{getDocumentTypeLabel(document)}</span>
            <span className={`pill pill--${document.parse_status}`}>{document.parse_status}</span>
          </div>
        </div>
        <dl className="detail-focus__grid">
          <div>
            <dt>Type</dt>
            <dd>{getDocumentTypeLabel(document)}</dd>
          </div>
          <div>
            <dt>Mime type</dt>
            <dd>{document.mime_type ?? 'Unknown'}</dd>
          </div>
          <div>
            <dt>Updated</dt>
            <dd>{formatDateTime(document.modified_at)}</dd>
          </div>
          <div>
            <dt>Indexed</dt>
            <dd>{formatDateTime(document.indexed_at)}</dd>
          </div>
          <div>
            <dt>Size</dt>
            <dd>{formatFileSize(document.size_bytes)}</dd>
          </div>
          <div>
            <dt>Owner</dt>
            <dd>{document.owner_external_id ?? 'Unknown'}</dd>
          </div>
        </dl>
        {document.parse_error ? <p className="error-banner">{document.parse_error}</p> : null}
      </section>
      <dl className="meta-grid">
        <div>
          <dt>Parse status</dt>
          <dd>{document.parse_status}</dd>
        </div>
        <div>
          <dt>Sync status</dt>
          <dd>{document.sync_status}</dd>
        </div>
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
        <header className="document-preview__header">
          <div>
            <h4>Original Preview</h4>
            <p>{document.source_url ? 'Embedded from the original document source.' : 'Original preview is unavailable for this document.'}</p>
          </div>
          {document.source_url ? (
            <a href={document.source_url} target="_blank" rel="noreferrer">
              Open original
            </a>
          ) : null}
        </header>
        {document.source_url ? (
          <iframe
            key={document.id}
            className="document-preview__frame"
            src={document.source_url}
            title={`Preview of ${document.file_name}`}
            loading="lazy"
          />
        ) : (
          <p className="empty-state">No source URL is available for this document preview.</p>
        )}
      </section>
    </div>
  );
}
