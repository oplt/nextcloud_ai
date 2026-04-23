import { getDocumentOriginalUrl } from '../api/client';
import DescriptionOutlinedIcon from '@mui/icons-material/DescriptionOutlined';
import { AppCard } from './ui/AppCard';
import type { ChatActiveContextDocument, ChatSource } from '../types/api';

type SourcePanelProps = {
  sources: ChatSource[];
  activeContextDocuments?: ChatActiveContextDocument[];
};

type SourceGroup = {
  document_id: string;
  file_name: string;
  file_path: string;
  maxScore: number;
  chunks: ChatSource[];
};

// ─── Helpers ──────────────────────────────────────────────────
function groupByDocument(sources: ChatSource[]): SourceGroup[] {
  const map = new Map<string, SourceGroup>();

  for (const s of sources) {
    const existing = map.get(s.document_id);
    if (!existing) {
      map.set(s.document_id, {
        document_id: s.document_id,
        file_name:   s.file_name,
        file_path:   s.file_path,
        maxScore:    s.score,
        chunks:      [s],
      });
    } else {
      existing.maxScore = Math.max(existing.maxScore, s.score);
      existing.chunks.push(s);
    }
  }

  return [...map.values()]
    .map((g) => ({ ...g, chunks: [...g.chunks].sort((a, b) => b.score - a.score) }))
    .sort((a, b) => b.maxScore - a.maxScore);
}

function locationLabel(source: ChatSource): string {
  const parts: string[] = [];
  if (source.page_number != null)  parts.push(`Page ${source.page_number}`);
  if (source.section_title)        parts.push(source.section_title);
  else if (source.heading_path)    parts.push(source.heading_path);
  return parts.join(' · ');
}

// ─── Sub-components ───────────────────────────────────────────
function SourceCard({ group }: { group: SourceGroup }) {
  const pct = Math.round(group.maxScore * 100);
  const sourceUrl = getDocumentOriginalUrl(group.document_id);

  return (
    <a
      className="source-card source-card--interactive"
      href={sourceUrl}
      target="_blank"
      rel="noreferrer"
      aria-label={`Open ${group.file_name} in a new window`}
    >
      <div className="source-card__header">
        <strong className="source-card__name">{group.file_name}</strong>
        <div className="source-card__meta">
          <span className="source-card__score">{pct}%</span>
          <span className="source-card__link">Open original ↗</span>
        </div>
      </div>
      <span className="source-card__path" title={group.file_path}>
        {group.file_path}
      </span>
      <div
        className="source-score-bar"
        role="meter"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`Relevance ${pct}%`}
      >
        <div className="source-score-bar__fill" style={{ width: `${pct}%` }} />
      </div>
      <div className="source-card__chunks">
        {group.chunks.map((chunk) => {
          const loc = locationLabel(chunk);
          return (
            <div key={chunk.chunk_id} className="source-card__chunk">
              {loc ? <span className="source-card__location">{loc}</span> : null}
              <p className="source-card__snippet">{chunk.snippet}</p>
            </div>
          );
        })}
      </div>
    </a>
  );
}

function ContextCard({ document }: { document: ChatActiveContextDocument }) {
  const sourceUrl = getDocumentOriginalUrl(document.document_id);

  return (
    <a
      className="source-card source-card--context source-card--interactive"
      href={sourceUrl}
      target="_blank"
      rel="noreferrer"
      aria-label={`Open ${document.file_name} in a new window`}
    >
      <div className="source-card__header">
        <strong className="source-card__name">{document.file_name}</strong>
        <span className="source-card__link">Open original ↗</span>
      </div>
      <span className="source-card__path" title={document.file_path}>
        {document.file_path}
      </span>
    </a>
  );
}

function EmptySources() {
  return (
    <div className="empty-state">
      <div className="empty-state-icon" aria-hidden="true">
        <DescriptionOutlinedIcon fontSize="medium" />
      </div>
      <span>Sources appear here after retrieval.</span>
    </div>
  );
}

// ─── SourcePanel ──────────────────────────────────────────────
export function SourcePanel({ sources, activeContextDocuments = [] }: SourcePanelProps) {
  const groups = groupByDocument(sources);

  return (
    <AppCard component="aside" className="card source-panel">
      <header className="panel-header">
        <h3>Sources for this answer</h3>
        {groups.length > 0 ? <span>{groups.length}</span> : null}
      </header>

      {groups.length === 0 ? (
        <EmptySources />
      ) : (
        <div className="source-list">
          {groups.map((g) => (
            <SourceCard key={g.document_id} group={g} />
          ))}
        </div>
      )}

      {activeContextDocuments.length > 0 ? (
        <>
          <header className="panel-header source-panel__subheader">
            <h4>Active context</h4>
            <span>{activeContextDocuments.length}</span>
          </header>
          <div className="source-list source-list--context">
            {activeContextDocuments.map((doc) => (
              <ContextCard key={doc.document_id} document={doc} />
            ))}
          </div>
        </>
      ) : null}
    </AppCard>
  );
}
