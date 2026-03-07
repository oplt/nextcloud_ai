import type { ChatSource } from '../types/api';

type SourcePanelProps = {
  sources: ChatSource[];
};

export function SourcePanel({ sources }: SourcePanelProps) {
  return (
    <aside className="card source-panel">
      <header className="panel-header">
        <h3>Sources</h3>
        <span>{sources.length}</span>
      </header>
      {sources.length === 0 ? <p className="empty-state">Sources appear here after retrieval.</p> : null}
      <div className="source-list">
        {sources.map((source) => (
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
