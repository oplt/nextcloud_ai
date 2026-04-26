import { useCallback, useMemo, useState } from 'react';
import Alert from '@mui/material/Alert';
import ButtonBase from '@mui/material/ButtonBase';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';

import { ChatInput } from '../components/ChatInput';
import { ChatWindow } from '../components/ChatWindow';
import { SourcePanel } from '../components/SourcePanel';
import { AppButton } from '../components/ui/AppButton';
import { AppCard } from '../components/ui/AppCard';
import { AppCheckbox } from '../components/ui/AppCheckbox';
import { AppSelectField } from '../components/ui/AppSelectField';
import {
  buildSourcesByMessageId,
  getLastAssistantMessageId,
  getPanelSources,
  mergeActiveContextDocuments,
} from '../features/chat/chatState';
import { AppTextField } from '../components/ui/AppTextField';
import { ConfirmDialog } from '../components/ui/ConfirmDialog';
import { HeroCardSkeleton, StatCardSkeleton } from '../components/ui/Skeleton';
import type {
  ChatActiveContextDocument,
  ChatAskResponse,
  ChatMessage,
  ChatSessionDetail,
  ChatSessionSummary,
  ChatSource,
  Connector,
  DocumentSummary,
  RetrievalFilterFormState,
  User,
} from '../types/api';

type OverviewPageProps = {
  user: User;
  connectors: Connector[];
  documents: DocumentSummary[];
  sessions: ChatSessionSummary[];
  activeSession: ChatSessionDetail | null;
  loading: boolean;
  workspaceLoading: boolean;
  workspaceError: string | null;
  chatError: string | null;
  chatFilters: RetrievalFilterFormState;
  availableMimeTypes: string[];
  onSelectSession: (sessionId: string) => Promise<void>;
  onAsk: (question: string) => Promise<ChatAskResponse>;
  onNewChat: () => void;
  onDeleteSessions: (sessionIds: string[]) => Promise<void>;
  onChatFilterChange: (patch: Partial<RetrievalFilterFormState>) => void;
  onResetChatFilters: () => void;
};

type StatCardData = { label: string; value: string };
type SourcesState = Record<string, ChatSource[]>;

function StatCard({ label, value }: StatCardData) {
  return (
    <AppCard className="card stat-card stat-card--compact">
      <span className="stat-card__label">{label}</span>
      <strong className="stat-card__value">{value}</strong>
    </AppCard>
  );
}

export function OverviewPage({
  user,
  connectors,
  documents,
  sessions,
  activeSession,
  loading,
  workspaceLoading,
  workspaceError,
  chatError,
  chatFilters,
  availableMimeTypes,
  onSelectSession,
  onAsk,
  onNewChat,
  onDeleteSessions,
  onChatFilterChange,
  onResetChatFilters,
}: OverviewPageProps) {
  const stats = useMemo<StatCardData[]>(
    () => [
      { label: 'Connectors', value: connectors.length.toString() },
      { label: 'Documents', value: documents.length.toString() },
      { label: 'Chats', value: sessions.length.toString() },
      { label: 'Role', value: user.role?.name ?? (user.is_superuser ? 'admin' : user.auth_provider) },
    ],
    [connectors.length, documents.length, sessions.length, user.auth_provider, user.is_superuser, user.role?.name],
  );

  const displayName = user.full_name ?? user.username;
  const displayEmail = user.email ?? user.external_subject ?? 'No email attached';
  const activeSessionId = activeSession?.id ?? null;

  const baseSourcesByMessageId = useMemo(
    () => buildSourcesByMessageId(activeSession?.messages ?? []),
    [activeSession?.messages],
  );
  const [sourceOverrides, setSourceOverrides] = useState<{ sessionId: string | null; data: SourcesState }>({
    sessionId: null,
    data: {},
  });
  const [selectedMessageState, setSelectedMessageState] = useState<{ sessionId: string | null; messageId: string | null }>({
    sessionId: null,
    messageId: null,
  });
  const [contextOverrideState, setContextOverrideState] = useState<{
    sessionId: string | null;
    docs: ChatActiveContextDocument[] | null;
  }>({ sessionId: null, docs: null });
  const [selectedSessionIds, setSelectedSessionIds] = useState<Set<string>>(new Set());
  const [sessionDeleteOpen, setSessionDeleteOpen] = useState(false);

  const sessionOverrides = useMemo(
    () => (sourceOverrides.sessionId === activeSessionId ? sourceOverrides.data : {}),
    [activeSessionId, sourceOverrides.data, sourceOverrides.sessionId],
  );
  const sourcesByMessageId = useMemo(
    () => ({ ...baseSourcesByMessageId, ...sessionOverrides }),
    [baseSourcesByMessageId, sessionOverrides],
  );

  const defaultActiveMessageId = useMemo(
    () => getLastAssistantMessageId(activeSession?.messages ?? []),
    [activeSession?.messages],
  );
  const activeMessageId =
    selectedMessageState.sessionId === activeSessionId
      ? selectedMessageState.messageId
      : defaultActiveMessageId;

  const panelSources = useMemo(
    () => getPanelSources(sourcesByMessageId, activeMessageId),
    [activeMessageId, sourcesByMessageId],
  );
  const activeContextDocs = useMemo(() => {
    if (contextOverrideState.sessionId === activeSessionId && contextOverrideState.docs) {
      return contextOverrideState.docs;
    }
    return mergeActiveContextDocuments(panelSources, activeSession?.active_context_documents ?? []);
  }, [activeSession?.active_context_documents, activeSessionId, contextOverrideState.docs, contextOverrideState.sessionId, panelSources]);

  const isSelectionMode = selectedSessionIds.size > 0;
  const availableSessionIds = useMemo(() => new Set(sessions.map((session) => session.id)), [sessions]);
  const safeSelectedSessionIds = useMemo(
    () => Array.from(selectedSessionIds).filter((id) => availableSessionIds.has(id)),
    [availableSessionIds, selectedSessionIds],
  );
  const allSessionsSelected = sessions.length > 0 && safeSelectedSessionIds.length === sessions.length;
  const hasActiveChatFilters = Object.values(chatFilters).some(Boolean);

  const handleAsk = useCallback(
    async (question: string): Promise<void> => {
      const response = await onAsk(question);
      const responseSources =
        (response.cited_sources?.length ? response.cited_sources : null) ??
        response.sources ??
        [];
      const responseSessionId = response.session_id;

      setSourceOverrides((current) => ({
        sessionId: responseSessionId,
        data:
          current.sessionId === responseSessionId
            ? {
                ...current.data,
                [response.assistant_message_id]: responseSources,
              }
            : { [response.assistant_message_id]: responseSources },
      }));
      setSelectedMessageState({
        sessionId: responseSessionId,
        messageId: response.assistant_message_id,
      });
      setContextOverrideState({
        sessionId: responseSessionId,
        docs:
          response.active_context_documents ??
          mergeActiveContextDocuments(responseSources, []),
      });
    },
    [onAsk],
  );

  const openSessionDeleteDialog = useCallback(() => {
    if (safeSelectedSessionIds.length === 0) {
      return;
    }
    setSessionDeleteOpen(true);
  }, [safeSelectedSessionIds]);

  const confirmSessionDelete = useCallback(async () => {
    if (safeSelectedSessionIds.length === 0) {
      return;
    }
    await onDeleteSessions(safeSelectedSessionIds);
    setSelectedSessionIds(new Set());
    setSessionDeleteOpen(false);
  }, [onDeleteSessions, safeSelectedSessionIds]);

  const messages: ChatMessage[] = activeSession?.messages ?? [];

  return (
    <div className="overview-stack">
      {workspaceError ? (
        <Alert severity="error" className="page-alert">
          {workspaceError}
        </Alert>
      ) : null}
      {workspaceLoading ? (
        <span className="visually-hidden" role="status" aria-live="polite">
          Loading connectors, documents, and chat list.
        </span>
      ) : null}
      {chatError ? (
        <Alert severity="error" className="page-alert">
          {chatError}
        </Alert>
      ) : null}

      <section className="overview-grid overview-grid--summary" aria-label="Summary statistics">
        {workspaceLoading ? (
          <>
            <StatCardSkeleton />
            <StatCardSkeleton />
            <StatCardSkeleton />
            <StatCardSkeleton />
            <HeroCardSkeleton />
          </>
        ) : (
          <>
            {stats.map((stat) => (
              <StatCard key={stat.label} {...stat} />
            ))}
            <AppCard className="card hero-card hero-card--compact">
              <span className="eyebrow">Current operator</span>
              <h2>{displayName}</h2>
              <p>{displayEmail}</p>
            </AppCard>
          </>
        )}
      </section>

      <AppCard component="section" className="card filter-card" aria-label="Chat retrieval filters">
        <header className="panel-header">
          <div>
            <h3>Chat retrieval scope</h3>
            <p className="filter-card__meta">Limit grounded answers by connector, type, path, or date range.</p>
          </div>
          <AppButton type="button" variant="outlined" onClick={onResetChatFilters} disabled={!hasActiveChatFilters}>
            Clear filters
          </AppButton>
        </header>

        <div className="filter-grid">
          <AppSelectField
            id="chat-filter-connector"
            label="Connector"
            value={chatFilters.connector_id}
            onChange={(event) => onChatFilterChange({ connector_id: event.target.value })}
            options={[
              { label: 'All connectors', value: '' },
              ...connectors.map((connector) => ({ label: connector.display_name, value: connector.id })),
            ]}
          />

          <AppSelectField
            id="chat-filter-mimetype"
            label="File type"
            value={chatFilters.mime_type}
            onChange={(event) => onChatFilterChange({ mime_type: event.target.value })}
            options={[
              { label: 'All types', value: '' },
              ...availableMimeTypes.map((mimeType) => ({ label: mimeType, value: mimeType })),
            ]}
          />

          <AppTextField
            label="Path prefix"
            value={chatFilters.path_prefix}
            onChange={(event) => onChatFilterChange({ path_prefix: event.target.value })}
            placeholder="/teams/sales"
          />

          <AppTextField
            label="Modified after"
            type="date"
            value={chatFilters.modified_after}
            onChange={(event) => onChatFilterChange({ modified_after: event.target.value })}
            InputLabelProps={{ shrink: true }}
          />

          <AppTextField
            label="Modified before"
            type="date"
            value={chatFilters.modified_before}
            onChange={(event) => onChatFilterChange({ modified_before: event.target.value })}
            InputLabelProps={{ shrink: true }}
          />
        </div>
      </AppCard>

      <section id="overview-chat" className="chat-layout home-chat" aria-label="Quick chat">
        <AppCard component="aside" className="card session-list">
          <header className="panel-header">
            <div className="session-list__heading">

              {sessions.length > 0 ? (
                <AppCheckbox
                  onChange={() =>
                    setSelectedSessionIds(
                      allSessionsSelected ? new Set() : new Set(sessions.map((session) => session.id)),
                    )
                  }
                  checked={allSessionsSelected}
                  aria-label="Select all sessions"
                />
              ) : null}
              <h3>Chatbot</h3>
            </div>
            <div className="session-list__actions">
              {isSelectionMode ? (
                <AppButton
                  onClick={openSessionDeleteDialog}
                  variant="outlined"
                  danger
                >
                  Delete ({safeSelectedSessionIds.length})
                </AppButton>
              ) : (
                <>
                  {sessions.length > 0 ? <Typography component="span">{sessions.length}</Typography> : null}
                  <AppButton type="button" className="session-list__new" onClick={onNewChat} disabled={loading}>
                    +
                  </AppButton>
                </>
              )}
            </div>
          </header>

          <div className="session-list__content">
            {sessions.length === 0 ? (
              <div className="empty-state"><span>No chats yet.</span></div>
            ) : (
              sessions.map((session) => {
                const checked = safeSelectedSessionIds.includes(session.id);
                return (
                  <div key={session.id} className="session-row">
                    <AppCheckbox
                      className="session-checkbox"
                      checked={checked}
                      onChange={(event) => {
                        setSelectedSessionIds((current) => {
                          const next = new Set(current);
                          if (event.target.checked) next.add(session.id);
                          else next.delete(session.id);
                          return next;
                        });
                      }}
                    />

                    <ButtonBase
                      type="button"
                      className={`session-button${session.id === activeSession?.id ? ' session-button--active' : ''}`}
                      onClick={() => void onSelectSession(session.id)}
                    >
                      <strong>{session.title}</strong>
                      <small>{new Date(session.updated_at).toLocaleString()}</small>
                    </ButtonBase>
                  </div>
                );
              })
            )}
          </div>
        </AppCard>

        <div className="chat-main">
          <ChatWindow
            messages={messages}
            loading={loading}
            activeAssistantMessageId={activeMessageId}
            onSelectAssistantMessage={(messageId) =>
              setSelectedMessageState({ sessionId: activeSessionId, messageId })
            }
          />
          <ChatInput onSubmit={handleAsk} disabled={loading} />
        </div>

        <SourcePanel sources={panelSources} activeContextDocuments={activeContextDocs} />
      </section>

      <ConfirmDialog
        open={sessionDeleteOpen}
        title={safeSelectedSessionIds.length === 1 ? 'Delete this chat?' : `Delete ${safeSelectedSessionIds.length} chats?`}
        description={
          <Stack gap={1}>
            <Typography component="p">
              {safeSelectedSessionIds.length === 1
                ? 'This permanently removes the selected conversation and its messages.'
                : 'This permanently removes the selected conversations and their messages.'}
            </Typography>
            <Typography component="p" className="dialog__note">This cannot be undone.</Typography>
          </Stack>
        }
        confirmLabel="Delete"
        cancelLabel="Cancel"
        variant="danger"
        onCancel={() => setSessionDeleteOpen(false)}
        onConfirm={() => void confirmSessionDelete()}
      />
    </div>
  );
}
