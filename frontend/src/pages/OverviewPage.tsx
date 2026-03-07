import type { Connector, DocumentSummary, SyncJob, User } from '../types/api';

type OverviewPageProps = {
  user: User;
  connectors: Connector[];
  documents: DocumentSummary[];
  jobs: SyncJob[];
};

export function OverviewPage({ user, connectors, documents, jobs }: OverviewPageProps) {
  const cards = [
    { label: 'Connectors', value: connectors.length.toString() },
    { label: 'Documents', value: documents.length.toString() },
    { label: 'Jobs', value: jobs.length.toString() },
    { label: 'Identity', value: user.auth_provider },
  ];

  return (
    <section className="overview-grid">
      {cards.map((card) => (
        <article key={card.label} className="card stat-card">
          <span>{card.label}</span>
          <strong>{card.value}</strong>
        </article>
      ))}
      <article className="card hero-card">
        <p className="eyebrow">Current operator</p>
        <h2>{user.full_name ?? user.username}</h2>
        <p>{user.email ?? user.external_subject ?? 'No email attached'}</p>
      </article>
    </section>
  );
}
