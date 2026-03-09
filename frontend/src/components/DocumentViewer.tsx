import { getDocumentOriginalUrl } from '../api/client';
import type { DocumentDetail } from '../types/api';
import { formatDateTime, formatFileSize, getDocumentTypeLabel } from '../utils/documentDisplay';

type DocumentViewerProps = {
  document: DocumentDetail | null;
  onReindex?: (documentId: string) => Promise<void>;
};

function EmptyState() {
  return (
    <div className="card detail-card">
      <div className="empty-state" style={{ minHeight: 240 }}>
        <div className="empty-state-icon" aria-hidden="true">
          <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M11 2H5a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7l-4-5z" strokeLinecap="round" strokeLinejoin="round" />
            <polyline points="11 2 11 7 16 7" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </div>
        <span>Select a document to view its details.</span>
      </div>
    </div>
  );
}

export function DocumentViewer({ document, onReindex }: DocumentViewerProps) {
  if (!document) return <EmptyState />;
  const originalUrl = getDocumentOriginalUrl(document.id);

  return (
    <div className="card detail-card">
      {/* ── Header ── */}
      <header className="panel-header">
        <div style={{ minWidth: 0, flex: 1 }}>
          <h3 style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {document.file_name}
          </h3>
          <p style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--text-muted)', marginTop: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {document.file_path}
          </p>
        </div>
        {onReindex ? (
          <button
            type="button"
            className="btn-outline"
            onClick={() => void onReindex(document.id)}
          >
            Reindex
          </button>
        ) : null}
      </header>

      {/* ── Focus section ── */}
      <section className="detail-focus">
        <div className="detail-focus__header">
          <div>
            <span className="eyebrow">Selected document</span>
            <h4 style={{ fontFamily: 'var(--display)', fontSize: 15, fontWeight: 700, color: 'var(--text-primary)', letterSpacing: '-0.02em', marginTop: 6 }}>
              {document.file_name}
            </h4>
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

      {/* ── Meta grid ── */}
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

      {/* ── Preview ── */}
      <section className="document-preview">
        <div className="document-preview__header">
          <div>
            <h4>Original Preview</h4>
            <p>
              Previewed directly from Nextcloud through the configured connector.
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
    </div>
  );
}
