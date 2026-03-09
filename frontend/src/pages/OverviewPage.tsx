import { useCallback, useEffect, useMemo, useState } from 'react';
import { ChatInput } from '../components/ChatInput';
import { ChatWindow } from '../components/ChatWindow';
import { SourcePanel } from '../components/SourcePanel';
import {
  buildSourcesByMessageId,
  getLastAssistantMessageId,
  getPanelSources,
  mergeActiveContextDocuments,
} from '../features/chat/chatState';
import type {
  ChatActiveContextDocument,
  ChatAskResponse,
  ChatMessage,
  ChatSessionDetail,
  ChatSessionSummary,
  ChatSource,
  Connector,
  DocumentSummary,
  User,
} from '../types/api';

// ─── Types ────────────────────────────────────────────────────
type OverviewPageProps = {
  user: User;
  connectors: Connector[];
  documents: DocumentSummary[];
  sessions: ChatSessionSummary[];
  activeSession: ChatSessionDetail | null;
  loading: boolean;
  onSelectSession: (sessionId: string) => Promise<void>;
  onAsk: (question: string) => Promise<ChatAskResponse>;
  onNewChat: () => void;
  onDeleteSessions: (sessionIds: string[]) => Promise<void>;
};

// ─── Stat card ────────────────────────────────────────────────
type StatCardData = { label: string; value: string };

function StatCard({ label, value }: StatCardData) {
  return (
    <article className="card stat-card">
      <span className="stat-card__label">{label}</span>
      <strong className="stat-card__value">{value}</strong>
    </article>
  );
}

// ─── OverviewPage ─────────────────────────────────────────────
export function OverviewPage({
  user,
  connectors,
  documents,
  sessions,
  activeSession,
  loading,
  onSelectSession,
  onAsk,
  onNewChat,
  onDeleteSessions,
}: OverviewPageProps) {
  // Derived stats — stable references via useMemo
  const stats = useMemo<StatCardData[]>(
    () => [
      { label: 'Connectors', value: connectors.length.toString() },
      { label: 'Documents',  value: documents.length.toString() },
      { label: 'Chats',      value: sessions.length.toString() },
      { label: 'Identity',   value: user.auth_provider },
    ],
    [connectors.length, documents.length, sessions.length, user.auth_provider],
  );

  const displayName  = user.full_name ?? user.username;
  const displayEmail = user.email ?? user.external_subject ?? 'No email attached';

  // ── Chat state ──────────────────────────────────────────────
  const [sourcesByMessageId, setSourcesByMessageId] = useState<Record<string, ChatSource[]>>({});
  const [activeMessageId, setActiveMessageId]       = useState<string | null>(null);
  const [activeContextDocs, setActiveContextDocs]   = useState<ChatActiveContextDocument[]>([]);
  const [selectedSessionIds, setSelectedSessionIds] = useState<Set<string>>(new Set());
    const isSelectionMode = selectedSessionIds.size > 0;

    const toggleSelectAll = () => {
      if (selectedSessionIds.size === sessions.length) {
        setSelectedSessionIds(new Set());
      } else {
        setSelectedSessionIds(new Set(sessions.map((s) => s.id)));
      }
    };

    const handleDelete = async () => {
      if (window.confirm(`Delete ${selectedSessionIds.size} sessions?`)) {
        await onDeleteSessions(Array.from(selectedSessionIds));
        setSelectedSessionIds(new Set());
      }
    };

  // Hydrate from session
  useEffect(() => {
    if (!activeSession) {
      setSourcesByMessageId({});
      setActiveMessageId(null);
      setActiveContextDocs([]);
      return;
    }

    const messages    = activeSession.messages ?? [];
    const sourcesMap  = buildSourcesByMessageId(messages);
    const lastId      = getLastAssistantMessageId(messages);
    const lastSources = getPanelSources(sourcesMap, lastId);

    setSourcesByMessageId(sourcesMap);
    setActiveMessageId(lastId);
    setActiveContextDocs(mergeActiveContextDocuments(lastSources, []));
  }, [activeSession?.id, activeSession?.messages.length]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleAsk = useCallback(
    async (question: string): Promise<void> => {
      const response = await onAsk(question);
      const sources: ChatSource[] =
        (response.cited_sources?.length ? response.cited_sources : null) ??
        response.sources ??
        [];

      setSourcesByMessageId((prev) => ({
        ...prev,
        [response.assistant_message_id]: sources,
      }));
      setActiveMessageId(response.assistant_message_id);
      setActiveContextDocs(
        response.active_context_documents ??
          mergeActiveContextDocuments(sources, []),
      );
    },
    [onAsk],
  );

  const panelSources = useMemo(
    () => getPanelSources(sourcesByMessageId, activeMessageId),
    [sourcesByMessageId, activeMessageId],
  );

  const messages: ChatMessage[] = activeSession?.messages ?? [];

  return (
    <div className="overview-stack">
      {/* ── Stats row ── */}
      <section className="overview-grid" aria-label="Summary statistics">
        {stats.map((s) => (
          <StatCard key={s.label} {...s} />
        ))}

        <article className="card hero-card">
          <span className="eyebrow">Current operator</span>
          <h2>{displayName}</h2>
          <p>{displayEmail}</p>
        </article>
      </section>

      {/* ── Inline chat ── */}
      <section className="chat-layout home-chat" aria-label="Quick chat">
              <aside className="card session-list">
                <header className="panel-header">
                  <div className="session-list__heading">
                    <h3>Chatbot</h3>
                    {/* Select All Toggle */}
                    {sessions.length > 0 && (
                       <input
                        type="checkbox"
                        onChange={toggleSelectAll}
                        checked={selectedSessionIds.size === sessions.length && sessions.length > 0}
                        aria-label="Select all sessions"
                      />
                    )}
                  </div>
                  <div className="session-list__actions">
                    {isSelectionMode ? (
                      <button
                        className="session-list__delete"
                        onClick={handleDelete}
                        style={{ color: 'var(--error-red, red)' }}
                      >
                        Delete ({selectedSessionIds.size})
                      </button>
                    ) : (
                      <>
                        {sessions.length > 0 ? <span>{sessions.length}</span> : null}
                        <button type="button" className="session-list__new" onClick={onNewChat} disabled={loading}>
                          + New
                        </button>
                      </>
                    )}
                  </div>
                </header>

                <div className="session-list__content">
                  {sessions.length === 0 ? (
                    <div className="empty-state"><span>No chats yet.</span></div>
                  ) : (
                    sessions.map((s) => (
                      <div key={s.id} className="session-item-container" style={{ display: 'flex', alignItems: 'center' }}>
                        {/* Individual Checkbox */}
                        <input
                          type="checkbox"
                          className="session-checkbox"
                          checked={selectedSessionIds.has(s.id)}
                          onChange={(e) => {
                            const next = new Set(selectedSessionIds);
                            if (e.target.checked) next.add(s.id);
                            else next.delete(s.id);
                            setSelectedSessionIds(next);
                          }}
                          style={{ margin: '0 8px' }}
                        />

                        <button
                          type="button"
                          className={`session-button${s.id === activeSession?.id ? ' session-button--active' : ''}`}
                          onClick={() => void onSelectSession(s.id)}
                          style={{ flex: 1 }}
                        >
                          <strong>{s.title}</strong>
                          <small>{new Date(s.updated_at).toLocaleString()}</small>
                        </button>
                      </div>
                    ))
                  )}
                </div>
              </aside>

        <div className="chat-main">
          <ChatWindow
            messages={messages}
            loading={loading}
            activeAssistantMessageId={activeMessageId}
            onSelectAssistantMessage={setActiveMessageId}
          />
          <ChatInput onSubmit={handleAsk} disabled={loading} />
        </div>

        <SourcePanel sources={panelSources} activeContextDocuments={activeContextDocs} />
      </section>
    </div>
  );
}
