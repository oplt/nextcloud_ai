import { ChatInput } from '../components/ChatInput';
import { ChatWindow } from '../components/ChatWindow';
import { SourcePanel } from '../components/SourcePanel';
import type {
  ChatSessionDetail,
  ChatSessionSummary,
  ChatSource,
  Connector,
  DocumentSummary,
  User,
} from '../types/api';

type OverviewPageProps = {
  user: User;
  connectors: Connector[];
  documents: DocumentSummary[];
  sessions: ChatSessionSummary[];
  activeSession: ChatSessionDetail | null;
  sources: ChatSource[];
  loading: boolean;
  onSelectSession: (sessionId: string) => Promise<void>;
  onAsk: (question: string) => Promise<void>;
  onNewChat: () => void;
};

export function OverviewPage({
  user,
  connectors,
  documents,
  sessions,
  activeSession,
  sources,
  loading,
  onSelectSession,
  onAsk,
  onNewChat,
}: OverviewPageProps) {
  const cards = [
    { label: 'Connectors', value: connectors.length.toString() },
    { label: 'Documents', value: documents.length.toString() },
    { label: 'Chats', value: sessions.length.toString() },
    { label: 'Identity', value: user.auth_provider },
  ];

  return (
    <div className="overview-stack">
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

      <section className="chat-layout home-chat">
        <aside className="card session-list">
          <header className="panel-header">
            <h3>Chatbot</h3>
            <button type="button" className="session-list__new" onClick={onNewChat}>
              New chat
            </button>
          </header>
          {sessions.length === 0 ? <p className="empty-state">No chats yet. Start with a question.</p> : null}
          {sessions.map((session) => (
            <button
              key={session.id}
              type="button"
              className={`session-button${session.id === activeSession?.id ? ' session-button--active' : ''}`}
              onClick={() => void onSelectSession(session.id)}
            >
              <strong>{session.title}</strong>
              <small>{new Date(session.updated_at).toLocaleString()}</small>
            </button>
          ))}
        </aside>
        <div className="chat-main">
          <ChatWindow messages={activeSession?.messages ?? []} loading={loading} />
          <ChatInput onSubmit={onAsk} disabled={loading} />
        </div>
        <SourcePanel sources={sources} />
      </section>
    </div>
  );
}
