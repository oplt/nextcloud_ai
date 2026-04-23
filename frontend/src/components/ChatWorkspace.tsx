import { useCallback, useMemo, useState } from 'react';
import ButtonBase from '@mui/material/ButtonBase';
import ChatBubbleOutlineOutlinedIcon from '@mui/icons-material/ChatBubbleOutlineOutlined';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';

import { AppButton } from './ui/AppButton';
import { AppCard } from './ui/AppCard';
import { AppCheckbox } from './ui/AppCheckbox';
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
import { ConfirmDialog } from './ui/ConfirmDialog';

type ChatWorkspaceProps = {
  sessions: ChatSessionSummary[];
  activeSession: ChatSessionDetail | null;
  loading: boolean;
  onSelectSession: (sessionId: string) => Promise<void>;
  onDeleteSessions?: (sessionIds: string[]) => Promise<void>;
  onAsk: (question: string, activeContextDocumentIds?: string[]) => Promise<ChatAskResponse>;
  onNewChat?: () => void;
};

function truncate(value: string, max = 22): string {
  return value.length <= max ? value : `${value.slice(0, max).trimEnd()}…`;
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
  const map = new Map(candidates.map((document) => [document.document_id, document]));
  return ids
    .filter(Boolean)
    .map((id) => map.get(id) ?? { document_id: id, file_name: id, file_path: id });
}

function getSessionContextDocs(
  sources: ChatSource[],
  session: ChatSessionDetail,
): ChatActiveContextDocument[] {
  const explicit = session.active_context_documents ?? [];
  const known = mergeActiveContextDocuments(sources, explicit);
  const resolved = resolveContextDocsByIds(session.active_context_document_ids, known);

  if (resolved.length > 0) return resolved;
  if (known.length > 0) return known;
  return mergeActiveContextDocuments(sources, []);
}

function getResponseContextDocs(
  response: ChatAskResponse,
  sources: ChatSource[],
  fallback: ChatActiveContextDocument[],
): ChatActiveContextDocument[] {
  const explicit = response.active_context_documents ?? [];
  const known = mergeActiveContextDocuments(sources, [...fallback, ...explicit]);
  const resolved = resolveContextDocsByIds(response.active_context_document_ids, known);

  if (resolved.length > 0) return resolved;
  if (sources.length === 0 && explicit.length === 0) return fallback;
  return mergeActiveContextDocuments(sources, explicit);
}

function EmptySessions() {
  return (
    <div className="empty-state">
      <div className="empty-state-icon" aria-hidden="true">
        <ChatBubbleOutlineOutlinedIcon fontSize="medium" />
      </div>
      <span>No previous chats yet. Saved conversations will appear here.</span>
    </div>
  );
}

export function ChatWorkspace({
  sessions,
  activeSession,
  loading,
  onSelectSession,
  onDeleteSessions,
  onAsk,
  onNewChat,
}: ChatWorkspaceProps) {
  const activeSessionId = activeSession?.id ?? null;
  const baseSourcesByMessageId = useMemo(
    () => buildSourcesByMessageId(activeSession?.messages ?? []),
    [activeSession?.messages],
  );
  const [sourceOverrides, setSourceOverrides] = useState<{ sessionId: string | null; data: SourcesByMessageId }>({
    sessionId: null,
    data: {},
  });
  const [activeMessageState, setActiveMessageState] = useState<{ sessionId: string | null; messageId: string | null }>({
    sessionId: null,
    messageId: null,
  });
  const [contextState, setContextState] = useState<{ sessionId: string | null; docs: ChatActiveContextDocument[] | null }>({
    sessionId: null,
    docs: null,
  });
  const [selectionMode, setSelectionMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);

  const activeSources = useMemo(
    () => (sourceOverrides.sessionId === activeSessionId ? sourceOverrides.data : {}),
    [activeSessionId, sourceOverrides.data, sourceOverrides.sessionId],
  );
  const sourcesByMessageId = useMemo(
    () => ({ ...baseSourcesByMessageId, ...activeSources }),
    [activeSources, baseSourcesByMessageId],
  );
  const fallbackActiveMessageId = useMemo(
    () => getLastAssistantMessageId(activeSession?.messages ?? []),
    [activeSession?.messages],
  );
  const activeMessageId =
    activeMessageState.sessionId === activeSessionId
      ? activeMessageState.messageId
      : fallbackActiveMessageId;
  const panelSources = useMemo(
    () => getPanelSources(sourcesByMessageId, activeMessageId),
    [activeMessageId, sourcesByMessageId],
  );
  const activeContextDocs = useMemo(() => {
    if (contextState.sessionId === activeSessionId && contextState.docs) {
      return contextState.docs;
    }
    if (!activeSession) {
      return [];
    }
    return getSessionContextDocs(panelSources, activeSession);
  }, [activeSession, activeSessionId, contextState.docs, contextState.sessionId, panelSources]);
  const allIds = useMemo(() => sessions.map((session) => session.id), [sessions]);
  const availableIds = useMemo(() => new Set(allIds), [allIds]);
  const safeSelectedIds = useMemo(
    () => selectedIds.filter((id) => availableIds.has(id)),
    [availableIds, selectedIds],
  );
  const allSelected = sessions.length > 0 && safeSelectedIds.length === sessions.length;
  const hasSelected = safeSelectedIds.length > 0;

  const toggleSelectionMode = useCallback(() => {
    setSelectionMode((enabled) => {
      if (enabled) {
        setSelectedIds([]);
      }
      return !enabled;
    });
  }, []);

  const toggleSession = useCallback((id: string) => {
    setSelectedIds((current) =>
      current.includes(id) ? current.filter((value) => value !== id) : [...current, id],
    );
  }, []);

  const toggleAll = useCallback(() => {
    setSelectedIds((current) => (current.length === allIds.length ? [] : allIds));
  }, [allIds]);

  const confirmDeleteSelected = useCallback(async () => {
    if (!onDeleteSessions || !hasSelected) return;
    try {
      await onDeleteSessions(safeSelectedIds);
      setSelectedIds([]);
      setSelectionMode(false);
      setDeleteDialogOpen(false);
    } catch {
      setDeleteDialogOpen(false);
    }
  }, [hasSelected, onDeleteSessions, safeSelectedIds]);

  const handleAsk = useCallback(
    async (question: string): Promise<void> => {
      const response = await onAsk(question, activeContextDocs.map((document) => document.document_id));
      const sources = getResponseSources(response);

      setSourceOverrides((current) => ({
        sessionId: response.session_id,
        data:
          current.sessionId === response.session_id
            ? { ...current.data, [response.assistant_message_id]: sources }
            : { [response.assistant_message_id]: sources },
      }));
      setActiveMessageState({
        sessionId: response.session_id,
        messageId: response.assistant_message_id,
      });
      setContextState((current) => ({
        sessionId: response.session_id,
        docs: getResponseContextDocs(
          response,
          sources,
          current.sessionId === response.session_id ? current.docs ?? [] : [],
        ),
      }));
    },
    [activeContextDocs, onAsk],
  );

  const messages: ChatMessage[] = activeSession?.messages ?? [];

  return (
    <section className="chat-layout">
      <AppCard component="aside" className="card session-list">
        <header className="panel-header">
          <div className="session-list__heading">
            <h3>Chats</h3>
            {sessions.length > 0 && onDeleteSessions ? (
              <AppButton
                type="button"
                variant="outlined"
                className="session-list__select-toggle"
                onClick={toggleSelectionMode}
                disabled={loading}
              >
                {selectionMode ? 'Cancel' : 'Select'}
              </AppButton>
            ) : null}
          </div>

          <div className="session-list__actions">
            {sessions.length > 0 ? <span>{sessions.length}</span> : null}
            {selectionMode && onDeleteSessions ? (
              <AppButton
                type="button"
                variant="outlined"
                danger
                className="session-list__delete"
                onClick={() => setDeleteDialogOpen(true)}
                disabled={loading || !hasSelected}
              >
                Delete
              </AppButton>
            ) : null}
            {onNewChat ? (
              <AppButton
                type="button"
                className="session-list__new"
                onClick={onNewChat}
                disabled={loading}
              >
                + New
              </AppButton>
            ) : null}
          </div>
        </header>

        {selectionMode && sessions.length > 0 ? (
          <div className="session-list__bulk-actions">
            <label className="session-list__select-all">
              <AppCheckbox
                checked={allSelected}
                onChange={toggleAll}
                disabled={loading}
              />
              <span>Select all</span>
            </label>
            <Typography component="small">
              {hasSelected ? `${safeSelectedIds.length} selected` : 'Choose chats to delete'}
            </Typography>
          </div>
        ) : null}

        <div className="session-list__content">
          {sessions.length === 0 ? (
            <EmptySessions />
          ) : (
            sessions.map((session) => (
              <div key={session.id} className="session-row">
                {selectionMode ? (
                  <label className="session-row__checkbox" aria-label={`Select ${session.title}`}>
                    <AppCheckbox
                      checked={safeSelectedIds.includes(session.id)}
                      onChange={() => toggleSession(session.id)}
                      disabled={loading}
                    />
                  </label>
                ) : null}
                <ButtonBase
                  type="button"
                  className={`session-button${session.id === activeSession?.id ? ' session-button--active' : ''}`}
                  onClick={() => void onSelectSession(session.id)}
                >
                  <strong>{truncate(session.title)}</strong>
                  <small>{new Date(session.updated_at).toLocaleString()}</small>
                </ButtonBase>
              </div>
            ))
          )}
        </div>
      </AppCard>

      <div className="chat-main">
        <ChatWindow
          messages={messages}
          loading={loading}
          activeAssistantMessageId={activeMessageId}
          onSelectAssistantMessage={(messageId) =>
            setActiveMessageState({ sessionId: activeSessionId, messageId })
          }
        />
        <ChatInput onSubmit={handleAsk} disabled={loading} />
      </div>

      <SourcePanel sources={panelSources} activeContextDocuments={activeContextDocs} />

      <ConfirmDialog
        open={deleteDialogOpen}
        title={
          safeSelectedIds.length === 1 ? 'Delete this chat?' : `Delete ${safeSelectedIds.length} chats?`
        }
        description={
          <Stack gap={1}>
            <Typography component="p">
              {safeSelectedIds.length === 1
                ? 'This permanently removes the conversation and its messages.'
                : 'This permanently removes the selected conversations and their messages.'}
            </Typography>
            <Typography component="p" className="dialog__note">This cannot be undone.</Typography>
          </Stack>
        }
        confirmLabel="Delete"
        cancelLabel="Cancel"
        variant="danger"
        onCancel={() => setDeleteDialogOpen(false)}
        onConfirm={() => void confirmDeleteSelected()}
      />
    </section>
  );
}
