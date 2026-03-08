import type { ChatSessionDetail, ChatSessionSummary, ChatSource } from '../types/api';
import { ChatInput } from '../components/ChatInput';
import { ChatWindow } from '../components/ChatWindow';
import { SourcePanel } from '../components/SourcePanel';

type ChatPageProps = {
  sessions: ChatSessionSummary[];
  activeSession: ChatSessionDetail | null;
  sources: ChatSource[];
  loading: boolean;
  onSelectSession: (sessionId: string) => Promise<void>;
  onAsk: (question: string) => Promise<void>;
};

export function ChatPage({
  sessions,
  activeSession,
  sources,
  loading,
  onSelectSession,
  onAsk,
}: ChatPageProps) {
  return (
    <section className="chat-layout">
      <aside className="card session-list">
        <header className="panel-header">
          <h3>Chats</h3>
          <span>{sessions.length}</span>
        </header>
        <div className="session-list__content">
          {sessions.map((session) => (
            <button
              key={session.id}
              type="button"
              className="session-button"
              onClick={() => void onSelectSession(session.id)}
            >
              <strong>{session.title}</strong>
              <small>{new Date(session.updated_at).toLocaleString()}</small>
            </button>
          ))}
        </div>
      </aside>
      <div className="chat-main">
        <ChatWindow messages={activeSession?.messages ?? []} loading={loading} />
        <ChatInput onSubmit={onAsk} disabled={loading} />
      </div>
      <SourcePanel sources={sources} />
    </section>
  );
}
