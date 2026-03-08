import type { ChatSource } from '../types/api';

type SourcePanelProps = {
  sources: ChatSource[];
};

function dedupeSourcesByDocument(sources: ChatSource[]): ChatSource[] {
  const byDocument = new Map<string, ChatSource>();

  for (const source of sources) {
    const existing = byDocument.get(source.document_id);
    if (!existing || source.score > existing.score) {
      byDocument.set(source.document_id, source);
    }
  }

  return [...byDocument.values()].sort((left, right) => right.score - left.score);
}

export function SourcePanel({ sources }: SourcePanelProps) {
  const uniqueSources = dedupeSourcesByDocument(sources);

  return (
    <aside className="card source-panel">
      <header className="panel-header">
        <h3>Sources</h3>
        <span>{uniqueSources.length}</span>
      </header>
      {uniqueSources.length === 0 ? <p className="empty-state">Sources appear here after retrieval.</p> : null}
      <div className="source-list">
        {uniqueSources.map((source) => (
          <article key={source.chunk_id} className="source-card">
            <strong>{source.file_name}</strong>
            <p>{source.snippet}</p>
            <footer>
              <span>{source.file_path}</span>
              <span>{Math.round(source.score * 100)}%</span>
            </footer>
          </article>
        ))}
      </div>
    </aside>
  );
}
