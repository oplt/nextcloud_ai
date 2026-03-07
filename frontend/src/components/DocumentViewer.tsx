import type { DocumentDetail } from '../types/api';

type DocumentViewerProps = {
  document: DocumentDetail | null;
  onReindex?: (documentId: string) => Promise<void>;
};

export function DocumentViewer({ document, onReindex }: DocumentViewerProps) {
  if (!document) {
    return (
      <div className="card detail-card">
        <p className="empty-state">Select a document to inspect chunks and permissions.</p>
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
      <section className="chunk-list">
        {document.chunks.map((chunk) => (
          <article key={chunk.id} className="chunk-card">
            <header>
              <strong>Chunk {chunk.chunk_index + 1}</strong>
              <span>{chunk.page_number ? `Page ${chunk.page_number}` : `${chunk.token_count ?? 0} tokens`}</span>
            </header>
            <p>{chunk.content}</p>
          </article>
        ))}
      </section>
    </div>
  );
}
