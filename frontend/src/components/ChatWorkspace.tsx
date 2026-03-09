import { useCallback, useEffect, useMemo, useState } from 'react';

import type {
  ChatActiveContextDocument,
  ChatAskResponse,
  ChatMessage,
  ChatSessionDetail,
  ChatSessionSummary,
  ChatSource,
} from '../types/api';
import {
  buildSourcesByMessageId,
  getLastAssistantMessageId,
  getPanelSources,
  mergeActiveContextDocuments,
  type SourcesByMessageId,
} from '../features/chat/chatState';
import { ChatInput } from './ChatInput';
import { ChatWindow } from './ChatWindow';
import { SourcePanel } from './SourcePanel';

// ─── Types ────────────────────────────────────────────────────
type ChatWorkspaceProps = {
  sessions: ChatSessionSummary[];
  activeSession: ChatSessionDetail | null;
  loading: boolean;
  onSelectSession: (sessionId: string) => Promise<void>;
  onDeleteSessions?: (sessionIds: string[]) => Promise<void>;
  onAsk: (question: string, activeContextDocumentIds?: string[]) => Promise<ChatAskResponse>;
  onNewChat?: () => void;
};

// ─── Helpers ─────────────────────────────────────────────────
function truncate(s: string, max = 22): string {
  return s.length <= max ? s : s.slice(0, max).trimEnd() + '…';
}

function getResponseSources(response: ChatAskResponse): ChatSource[] {
  if (Array.isArray(response.cited_sources) && response.cited_sources.length > 0) {
    return response.cited_sources;
  }
  return response.sources ?? [];
}

function resolveContextDocsByIds(
  ids: string[] | undefined,
  candidates: ChatActiveContextDocument[],
): ChatActiveContextDocument[] {
  if (!Array.isArray(ids) || ids.length === 0) return [];
  const map = new Map(candidates.map((d) => [d.document_id, d]));
  return ids
    .filter(Boolean)
    .map(
      (id) =>
        map.get(id) ?? { document_id: id, file_name: id, file_path: id },
    );
}

function getSessionContextDocs(
  sources: ChatSource[],
  session: ChatSessionDetail,
): ChatActiveContextDocument[] {
  const sourceBacked = mergeActiveContextDocuments(sources, []);
  const explicit = resolveContextDocsByIds(session.active_context_document_ids, sourceBacked);
  return explicit.length > 0 ? explicit : sourceBacked;
}

function getResponseContextDocs(
  response: ChatAskResponse,
  sources: ChatSource[],
  fallback: ChatActiveContextDocument[],
): ChatActiveContextDocument[] {
  const explicit = response.active_context_documents ?? [];
  const known    = mergeActiveContextDocuments(sources, [...fallback, ...explicit]);
  const resolved = resolveContextDocsByIds(response.active_context_document_ids, known);

  if (resolved.length > 0)      return resolved;
  if (sources.length === 0 && explicit.length === 0) return fallback;
  return mergeActiveContextDocuments(sources, explicit);
}

// ─── Empty state ──────────────────────────────────────────────
function EmptySessions() {
  return (
    <div className="empty-state">
      <div className="empty-state-icon" aria-hidden="true">
        <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5">
          <path d="M17 13a2 2 0 0 1-2 2H6l-3 3V5a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v8z" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </div>
      <span>No previous chats yet. Saved conversations will appear here.</span>
    </div>
  );
}

// ─── ChatWorkspace ────────────────────────────────────────────
export function ChatWorkspace({
  sessions,
  activeSession,
  loading,
  onSelectSession,
  onDeleteSessions,
  onAsk,
  onNewChat,
}: ChatWorkspaceProps) {
  const [sourcesByMessageId, setSourcesByMessageId] = useState<SourcesByMessageId>({});
  const [activeMessageId, setActiveMessageId]       = useState<string | null>(null);
  const [activeContextDocs, setActiveContextDocs]   = useState<ChatActiveContextDocument[]>([]);
  const [selectionMode, setSelectionMode]           = useState(false);
  const [selectedIds, setSelectedIds]               = useState<string[]>([]);

  // Hydrate sources from active session
  useEffect(() => {
    if (!activeSession) {
      setSourcesByMessageId({});
      setActiveMessageId(null);
      setActiveContextDocs([]);
      return;
    }

    const msgs    = activeSession.messages ?? [];
    const sources = buildSourcesByMessageId(msgs);
    const lastId  = getLastAssistantMessageId(msgs);
    const panel   = getPanelSources(sources, lastId);

    setSourcesByMessageId(sources);
    setActiveMessageId(lastId);
    setActiveContextDocs(getSessionContextDocs(panel, activeSession));
  }, [activeSession]);

  // Prune deleted sessions from selection
  useEffect(() => {
    const available = new Set(sessions.map((s) => s.id));
    setSelectedIds((cur) => cur.filter((id) => available.has(id)));
    if (sessions.length === 0) setSelectionMode(false);
  }, [sessions]);

  const panelSources  = useMemo(() => getPanelSources(sourcesByMessageId, activeMessageId), [sourcesByMessageId, activeMessageId]);
  const allIds        = useMemo(() => sessions.map((s) => s.id), [sessions]);
  const allSelected   = sessions.length > 0 && selectedIds.length === sessions.length;
  const hasSelected   = selectedIds.length > 0;

  // ── Selection handlers ───────────────────────────────────────
  const toggleSelectionMode = useCallback(() => {
    setSelectionMode((on) => { if (on) setSelectedIds([]); return !on; });
  }, []);

  const toggleSession = useCallback((id: string) => {
    setSelectedIds((cur) =>
      cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id],
    );
  }, []);

  const toggleAll = useCallback(() => {
    setSelectedIds((cur) => (cur.length === allIds.length ? [] : allIds));
  }, [allIds]);

  const handleDeleteSelected = useCallback(async () => {
    if (!onDeleteSessions || !hasSelected) return;
    const msg =
      selectedIds.length === 1
        ? 'Delete this chat session?'
        : `Delete ${selectedIds.length} chat sessions?`;
    if (!window.confirm(msg)) return;
    try {
      await onDeleteSessions(selectedIds);
      setSelectedIds([]);
      setSelectionMode(false);
    } catch {
      // keep selection for retry
    }
  }, [onDeleteSessions, hasSelected, selectedIds]);

  // ── Ask ──────────────────────────────────────────────────────
  const handleAsk = useCallback(
    async (question: string): Promise<void> => {
      const response     = await onAsk(question, activeContextDocs.map((d) => d.document_id));
      const sources      = getResponseSources(response);

      setSourcesByMessageId((cur) => ({ ...cur, [response.assistant_message_id]: sources }));
      setActiveMessageId(response.assistant_message_id);
      setActiveContextDocs((cur) => getResponseContextDocs(response, sources, cur));
    },
    [onAsk, activeContextDocs],
  );

  const messages: ChatMessage[] = activeSession?.messages ?? [];

  return (
    <section className="chat-layout">
      {/* ── Session sidebar ── */}
      <aside className="card session-list">
        <header className="panel-header">
          <div className="session-list__heading">
            <h3>Chats</h3>
            {sessions.length > 0 && onDeleteSessions ? (
              <button
                type="button"
                className="session-list__select-toggle"
                onClick={toggleSelectionMode}
                disabled={loading}
              >
                {selectionMode ? 'Cancel' : 'Select'}
              </button>
            ) : null}
          </div>

          <div className="session-list__actions">
            {sessions.length > 0 ? <span>{sessions.length}</span> : null}
            {selectionMode && onDeleteSessions ? (
              <button
                type="button"
                className="session-list__delete"
                onClick={() => void handleDeleteSelected()}
                disabled={loading || !hasSelected}
              >
                Delete
              </button>
            ) : null}
            {onNewChat ? (
              <button
                type="button"
                className="session-list__new"
                onClick={onNewChat}
                disabled={loading}
              >
                + New
              </button>
            ) : null}
          </div>
        </header>

        {selectionMode && sessions.length > 0 ? (
          <div className="session-list__bulk-actions">
            <label className="session-list__select-all">
              <input
                type="checkbox"
                checked={allSelected}
                onChange={toggleAll}
                disabled={loading}
              />
              <span>Select all</span>
            </label>
            <small>
              {hasSelected ? `${selectedIds.length} selected` : 'Choose chats to delete'}
            </small>
          </div>
        ) : null}

        <div className="session-list__content">
          {sessions.length === 0 ? (
            <EmptySessions />
          ) : (
            sessions.map((s) => (
              <div key={s.id} className="session-row">
                {selectionMode ? (
                  <label className="session-row__checkbox" aria-label={`Select ${s.title}`}>
                    <input
                      type="checkbox"
                      checked={selectedIds.includes(s.id)}
                      onChange={() => toggleSession(s.id)}
                      disabled={loading}
                    />
                  </label>
                ) : null}
                <button
                  type="button"
                  className={`session-button${s.id === activeSession?.id ? ' session-button--active' : ''}`}
                  onClick={() => void onSelectSession(s.id)}
                >
                  <strong>{truncate(s.title)}</strong>
                  <small>{new Date(s.updated_at).toLocaleString()}</small>
                </button>
              </div>
            ))
          )}
        </div>
      </aside>

      {/* ── Chat main ── */}
      <div className="chat-main">
        <ChatWindow
          messages={messages}
          loading={loading}
          activeAssistantMessageId={activeMessageId}
          onSelectAssistantMessage={setActiveMessageId}
        />
        <ChatInput onSubmit={handleAsk} disabled={loading} />
      </div>

      {/* ── Sources ── */}
      <SourcePanel sources={panelSources} activeContextDocuments={activeContextDocs} />
    </section>
  );
}
