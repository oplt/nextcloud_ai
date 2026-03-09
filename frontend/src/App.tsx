import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import {
  askChat,
  createConnector,
  deleteChatSession,
  deleteConnector,
  getChatSession,
  getDocument,
  listJobs,
  listChatSessions,
  listConnectors,
  listDocuments,
  reindexDocument,
  syncConnector,
  testConnector,
  updateConnector,
} from './api/client';
import { useSession } from './hooks/useSession';
import { ConnectorsPage } from './pages/ConnectorsPage';
import { DocumentsPage } from './pages/DocumentsPage';
import { JobsPage } from './pages/JobsPage';
import { LoginPage } from './pages/LoginPage';
import { OverviewPage } from './pages/OverviewPage';
import type {
  ChatAskResponse,
  ChatMessage,
  ChatSessionDetail,
  ChatSessionSummary,
  Connector,
  ConnectorPayload,
  DocumentDetail,
  DocumentSummary,
  SyncJob,
} from './types/api';

// ─── Types ────────────────────────────────────────────────────
type View = 'overview' | 'connectors' | 'documents' | 'jobs';

type NavItem = {
  key: View;
  label: string;
  heading: string;
  description: string;
  icon: React.ReactNode;
};

// ─── Nav icon components ──────────────────────────────────────
function HomeIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 9.5L10 3l7 6.5V17a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V9.5z" />
      <path d="M7 18v-6h6v6" />
    </svg>
  );
}

function ConnectorIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <rect x="2" y="3" width="6" height="4" rx="1" />
      <rect x="12" y="3" width="6" height="4" rx="1" />
      <rect x="7" y="13" width="6" height="4" rx="1" />
      <path d="M5 7v2a3 3 0 0 0 3 3h4a3 3 0 0 0 3-3V7" />
      <line x1="10" y1="12" x2="10" y2="13" />
    </svg>
  );
}

function DocumentIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 4a2 2 0 0 1 2-2h6l4 4v10a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V4z" />
      <polyline points="12 2 12 6 16 6" />
      <line x1="7" y1="10" x2="13" y2="10" />
      <line x1="7" y1="14" x2="11" y2="14" />
    </svg>
  );
}

function JobsIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="10" cy="10" r="7" />
      <path d="M10 6v4l2.5 2.5" />
      <path d="M6 3.5 4.5 2" />
      <path d="M14 3.5 15.5 2" />
    </svg>
  );
}

const navItems: NavItem[] = [
  {
    key: 'overview',
    label: 'Home',
    heading: 'Private company knowledge workspace',
    description: 'Track connector health, browse synced content, and work with the latest chat context.',
    icon: <HomeIcon />,
  },
  {
    key: 'connectors',
    label: 'Connectors',
    heading: 'Connector management',
    description: 'Configure Nextcloud sources, validate credentials, and run sync jobs from one place.',
    icon: <ConnectorIcon />,
  },
  {
    key: 'documents',
    label: 'Documents',
    heading: 'Document catalog',
    description: 'Review indexed files, inspect metadata, and requeue document parsing when needed.',
    icon: <DocumentIcon />,
  },
  {
    key: 'jobs',
    label: 'Jobs',
    heading: 'Operational job monitor',
    description: 'Track sync and reindex execution, watch failures, and follow retry activity in real time.',
    icon: <JobsIcon />,
  },
];

// ─── Helpers ─────────────────────────────────────────────────
function createLocalChatMessage(
  role: 'user' | 'assistant',
  content: string,
  sessionId: string | null,
): ChatMessage {
  const timestamp = new Date().toISOString();
  return {
    id: `local-${role}-${crypto.randomUUID()}`,
    session_id: sessionId ?? 'local-session',
    role,
    content,
    citations_json: null,
    model_name: null,
    created_at: timestamp,
    updated_at: timestamp,
  };
}

function getLastAssistantMessageId(messages: ChatMessage[]): string | null {
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i].role === 'assistant') return messages[i].id;
  }
  return null;
}

function extractActiveContextDocumentIds(messages: ChatMessage[]): string[] {
  const last = [...messages].reverse().find((m) => m.role === 'assistant');
  const citations = Array.isArray(last?.citations_json) ? last.citations_json : [];
  const ids: string[] = [];
  for (const c of citations) {
    const id = typeof c.document_id === 'string' ? c.document_id : null;
    if (id && !ids.includes(id)) ids.push(id);
  }
  return ids;
}

function getUserInitials(name: string | null | undefined): string {
  const parts = name?.trim().split(/\s+/).filter(Boolean) ?? [];
  if (!parts.length) return 'NC';
  return parts
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase() ?? '')
    .join('');
}

// ─── App ──────────────────────────────────────────────────────
function App() {
  const { user, loading, error, login, logout, refresh } = useSession();
  const [view, setView] = useState<View>('overview');

  // Data
  const [connectors, setConnectors]       = useState<Connector[]>([]);
  const [documents, setDocuments]         = useState<DocumentSummary[]>([]);
  const [jobs, setJobs]                   = useState<SyncJob[]>([]);
  const [sessions, setSessions]           = useState<ChatSessionSummary[]>([]);
  const [selectedDocument, setSelectedDocument] = useState<DocumentDetail | null>(null);
  const [selectedSession, setSelectedSession]   = useState<ChatSessionDetail | null>(null);
  const [pendingMessages, setPendingMessages]   = useState<ChatMessage[]>([]);
  const [jobsLoading, setJobsLoading] = useState(false);
  const [jobsRefreshing, setJobsRefreshing] = useState(false);
  const [jobsError, setJobsError] = useState<string | null>(null);
  const [jobsLastUpdatedAt, setJobsLastUpdatedAt] = useState<string | null>(null);

  // UI state
  const [busy, setBusy]   = useState(false);
  const [flash, setFlash] = useState<string | null>(null);

  const latestChatRequestId = useRef<string | null>(null);
  const jobsRequestInFlight = useRef(false);

  const selectedDocumentId = selectedDocument?.id ?? null;

  // Compose the view-friendly session (optimistic messages merged in)
  const activeSessionView = useMemo<ChatSessionDetail | null>(() => {
    if (selectedSession) {
      return pendingMessages.length === 0
        ? selectedSession
        : { ...selectedSession, messages: [...selectedSession.messages, ...pendingMessages] };
    }
    if (!user || pendingMessages.length === 0) return null;
    const first = pendingMessages[0];
    const last  = pendingMessages[pendingMessages.length - 1];
    return {
      id: 'local-session',
      user_id: user.id,
      title: first.content.slice(0, 80) || 'New chat',
      created_at: first.created_at,
      updated_at: last.updated_at,
      messages: pendingMessages,
    };
  }, [pendingMessages, selectedSession, user]);

  // ── Data loading ────────────────────────────────────────────
  const loadConnectors = useCallback(async () => {
    setConnectors(await listConnectors());
  }, []);

  const loadDocuments = useCallback(async () => {
    setDocuments(await listDocuments());
  }, []);

  const loadJobs = useCallback(async (options?: { silent?: boolean }) => {
    if (jobsRequestInFlight.current) {
      return;
    }

    const silent = options?.silent ?? false;
    jobsRequestInFlight.current = true;
    if (silent) {
      setJobsRefreshing(true);
    } else {
      setJobsLoading(true);
    }

    try {
      const nextJobs = await listJobs();
      setJobs(nextJobs);
      setJobsError(null);
      setJobsLastUpdatedAt(new Date().toISOString());
    } catch (e) {
      setJobsError(e instanceof Error ? e.message : 'Failed to load jobs');
    } finally {
      jobsRequestInFlight.current = false;
      if (silent) {
        setJobsRefreshing(false);
      } else {
        setJobsLoading(false);
      }
    }
  }, []);

  const refreshDocumentsView = useCallback(
    async (options?: { silent?: boolean }) => {
      try {
        await Promise.all([
          loadDocuments(),
          loadConnectors(),
          loadJobs({ silent: true }),
        ]);
      } catch (e) {
        if (options?.silent) {
          return;
        }
        setFlash(e instanceof Error ? e.message : 'Failed to load documents');
      }
    },
    [loadConnectors, loadDocuments, loadJobs],
  );

  const loadData = useCallback(async () => {
    const [nc, nd, ns] = await Promise.all([
      listConnectors(),
      listDocuments(),
      listChatSessions(),
    ]);
    setConnectors(nc);
    setDocuments(nd);
    setSessions(ns);
  }, []);

  useEffect(() => {
    if (!user) return;
    void loadData().catch((e: unknown) => {
      setFlash(e instanceof Error ? e.message : 'Failed to load dashboard data');
    });
  }, [user, loadData]);

  useEffect(() => {
    if (!user || view !== 'jobs') {
      return;
    }

    void loadJobs({ silent: jobs.length > 0 });

    const intervalId = window.setInterval(() => {
      if (document.visibilityState === 'hidden') {
        return;
      }
      void loadJobs({ silent: true });
    }, 5000);

    return () => {
      window.clearInterval(intervalId);
    };
  }, [jobs.length, loadJobs, user, view]);

  useEffect(() => {
    if (!user || view !== 'documents') {
      return;
    }

    void refreshDocumentsView();

    const intervalId = window.setInterval(() => {
      if (document.visibilityState === 'hidden') {
        return;
      }
      void refreshDocumentsView({ silent: true });
    }, 5000);

    return () => {
      window.clearInterval(intervalId);
    };
  }, [refreshDocumentsView, user, view]);

  // ── Feedback wrapper ────────────────────────────────────────
  const withFeedback = useCallback(
    async (work: () => Promise<void>, successMessage: string) => {
      setBusy(true);
      setFlash(null);
      try {
        await work();
        setFlash(successMessage);
      } catch (e) {
        setFlash(e instanceof Error ? e.message : 'Operation failed');
      } finally {
        setBusy(false);
      }
    },
    [],
  );

  // ── Connector handlers ──────────────────────────────────────
  const handleCreate = useCallback(
    async (payload: ConnectorPayload) => {
      await withFeedback(async () => {
        await createConnector(payload);
        await loadConnectors();
      }, 'Connector saved');
    },
    [withFeedback, loadConnectors],
  );

  const handleDelete = useCallback(
    async (connectorId: string) => {
      await withFeedback(async () => {
        await deleteConnector(connectorId);
        if (selectedDocument?.connector_id === connectorId) setSelectedDocument(null);
        await Promise.all([loadConnectors(), loadDocuments()]);
      }, 'Connector deleted');
    },
    [withFeedback, loadConnectors, loadDocuments, selectedDocument],
  );

  const handleTestConnector = useCallback(
    async (connectorId: string) => {
      await withFeedback(async () => {
        await testConnector(connectorId);
        await loadConnectors();
      }, 'Connector test passed');
    },
    [withFeedback, loadConnectors],
  );

  const handleSyncConnector = useCallback(
    async (connectorId: string, fullReindex = false) => {
      await withFeedback(async () => {
        await syncConnector(connectorId, fullReindex);
        await Promise.all([loadConnectors(), loadJobs({ silent: true })]);
      }, fullReindex ? 'Full reindex queued' : 'Sync queued');
    },
    [withFeedback, loadConnectors, loadJobs],
  );

  const handleToggleConnectorActive = useCallback(
    async (connectorId: string, nextActive: boolean) => {
      await withFeedback(async () => {
        await updateConnector(connectorId, { is_active: nextActive });
        await loadConnectors();
      }, nextActive ? 'Connector activated' : 'Connector deactivated');
    },
    [withFeedback, loadConnectors],
  );

  // ── Document handlers ───────────────────────────────────────
  const handleSelectDocument = useCallback(
    async (document: DocumentSummary) => {
      await withFeedback(async () => {
        const detail = await getDocument(document.id);
        setSelectedDocument(detail);
      }, `Loaded ${document.file_name}`);
    },
    [withFeedback],
  );

  const handleReindexDocument = useCallback(
    async (documentId: string) => {
      await withFeedback(async () => {
        await reindexDocument(documentId);
        await Promise.all([loadData(), loadJobs({ silent: true })]);
      }, 'Reindex queued');
    },
    [withFeedback, loadData, loadJobs],
  );

  // ── Chat handlers ───────────────────────────────────────────
  const handleSelectSession = useCallback(
    async (sessionId: string) => {
      await withFeedback(async () => {
        setPendingMessages([]);
        const detail = await getChatSession(sessionId);
        setSelectedSession(detail);
      }, 'Chat loaded');
    },
    [withFeedback],
  );

  const handleDeleteSessions = useCallback(
    async (ids: string[]) => {
      await withFeedback(async () => {
        await Promise.all(ids.map((id) => deleteChatSession(id)));
        setSessions((prev) => prev.filter((session) => !ids.includes(session.id)));

        if (selectedSession && ids.includes(selectedSession.id)) {
          setSelectedSession(null);
          setPendingMessages([]);
          latestChatRequestId.current = null;
        }
      }, ids.length === 1 ? 'Chat deleted' : `${ids.length} chats deleted`);
    },
    [selectedSession, withFeedback],
  );

  const handleAsk = useCallback(
    async (
      question: string,
      activeContextDocumentIds: string[] = [],
    ): Promise<ChatAskResponse> => {
      const requestId = crypto.randomUUID();
      latestChatRequestId.current = requestId;

      const sessionId    = selectedSession?.id ?? null;
      const currentMsgs  = activeSessionView?.messages ?? [];
      const parentMsgId  = getLastAssistantMessageId(currentMsgs);
      const contextDocIds = [...new Set([
        ...activeContextDocumentIds,
        ...extractActiveContextDocumentIds(currentMsgs),
      ])];
      const optimistic   = createLocalChatMessage('user', question, sessionId);

      setBusy(true);
      setFlash(null);
      setPendingMessages((p) => [...p, optimistic]);

      try {
        const response = await askChat({
          question,
          session_id: sessionId,
          parent_message_id: parentMsgId,
          active_context_document_ids: contextDocIds,
          request_id: requestId,
          top_k: 6,
        });

        if (latestChatRequestId.current !== requestId) return response;

        try {
          const [detail, nextSessions] = await Promise.all([
            getChatSession(response.session_id),
            listChatSessions(),
          ]);
          setSelectedSession(detail);
          setSessions(nextSessions);
          setPendingMessages([]);
        } catch (refreshErr) {
          const msg = refreshErr instanceof Error ? refreshErr.message : 'Failed to reload chat';
          setFlash(`Chat saved, but history refresh failed: ${msg}`);
          setPendingMessages([
            optimistic,
            createLocalChatMessage('assistant', response.answer, response.session_id),
          ]);
        }
        return response;
      } catch (e) {
        const msg = e instanceof Error ? e.message : 'Chat request failed';
        setFlash(msg);
        setPendingMessages([
          optimistic,
          createLocalChatMessage('assistant', `I could not complete this request: ${msg}`, sessionId),
        ]);
        throw e instanceof Error ? e : new Error(msg);
      } finally {
        if (latestChatRequestId.current === requestId) setBusy(false);
      }
    },
    [selectedSession, activeSessionView],
  );

  const handleNewChat = useCallback(() => {
    setSelectedSession(null);
    setPendingMessages([]);
    setFlash(null);
    latestChatRequestId.current = null;
  }, []);

  const handleLogout = useCallback(async () => {
    setBusy(true);
    setFlash(null);
    try {
      await logout();
      setView('overview');
      setConnectors([]);
      setDocuments([]);
      setJobs([]);
      setJobsLoading(false);
      setJobsRefreshing(false);
      setSessions([]);
      setSelectedDocument(null);
      setSelectedSession(null);
      setPendingMessages([]);
      setJobsError(null);
      setJobsLastUpdatedAt(null);
      latestChatRequestId.current = null;
      jobsRequestInFlight.current = false;
    } catch (e) {
      setFlash(e instanceof Error ? e.message : 'Sign out failed');
    } finally {
      setBusy(false);
    }
  }, [logout]);

  // ── Derived ─────────────────────────────────────────────────
  const currentView = useMemo(
    () => navItems.find((n) => n.key === view) ?? navItems[0],
    [view],
  );

  const userInitials = getUserInitials(user?.full_name ?? user?.username);

  // ── Render ───────────────────────────────────────────────────
  if (loading) return <div className="app-loading">Loading workspace</div>;
  if (!user)   return <LoginPage onLogin={login} error={error} />;

  return (
    <div className="app-shell">
      {/* ── Sidebar ── */}
      <aside className="sidebar">
        <div className="sidebar__brand">
          <div className="sidebar__logo">NC</div>
          <div className="sidebar__brand-text">
            <strong>Nextcloud AI</strong>
            <p>Knowledge cockpit</p>
          </div>
        </div>

        <nav className="sidebar__nav" aria-label="Primary navigation">
          {navItems.map((item, i) => (
            <button
              key={item.key}
              type="button"
              className={`sidebar__nav-item${item.key === view ? ' sidebar__nav-item--active' : ''}`}
              onClick={() => setView(item.key)}
              style={{ animationDelay: `${i * 40}ms` }}
              aria-current={item.key === view ? 'page' : undefined}
            >
              <span className="sidebar__nav-item-icon">{item.icon}</span>
              <span className="sidebar__nav-item-text">
                <strong>{item.label}</strong>
                <small>{item.heading}</small>
              </span>
            </button>
          ))}
        </nav>

        <div className="sidebar__footer">
          <div className="sidebar__user">
            <span className="sidebar__avatar">{userInitials}</span>
            <div className="sidebar__user-info">
              <strong>{user.full_name ?? user.username}</strong>
              <p>{user.email ?? 'No email synced'}</p>
            </div>
          </div>
          <div className="sidebar__actions">
            <button type="button" onClick={() => void refresh()}>
              Refresh
            </button>
            <button type="button" onClick={() => void handleLogout()}>
              Sign out
            </button>
          </div>
        </div>
      </aside>

      {/* ── Main ── */}
      <main className="app-main">
        <header className="app-header">
          <div className="app-header__left">
            <span className="eyebrow">Workspace</span>
            <h1>{currentView.heading}</h1>
            <p>{currentView.description}</p>
          </div>
          <div className="app-header__status">
            <span className={`status-pill${busy ? ' status-pill--busy' : ''}`}>
              {busy ? 'Working…' : 'Ready'}
            </span>
            {flash ? <span className="status-flash">{flash}</span> : null}
          </div>
        </header>

        <div className="app-content">
          {view === 'overview' ? (
            <OverviewPage
              user={user}
              connectors={connectors}
              documents={documents}
              sessions={sessions}
              activeSession={activeSessionView}
              loading={busy}
              onSelectSession={handleSelectSession}
              onAsk={handleAsk}
              onNewChat={handleNewChat}
              onDeleteSessions={handleDeleteSessions}
            />
          ) : null}

          {view === 'connectors' ? (
            <ConnectorsPage
              connectors={connectors}
              onCreate={handleCreate}
              onDelete={handleDelete}
              onTest={handleTestConnector}
              onSync={handleSyncConnector}
              onToggleActive={handleToggleConnectorActive}
            />
          ) : null}

          {view === 'documents' ? (
            <DocumentsPage
              documents={documents}
              selectedDocument={selectedDocument}
              selectedDocumentId={selectedDocumentId}
              onSelect={handleSelectDocument}
              onReindex={handleReindexDocument}
            />
          ) : null}

          {view === 'jobs' ? (
            <JobsPage
              jobs={jobs}
              connectors={connectors}
              loading={jobsLoading}
              refreshing={jobsRefreshing}
              error={jobsError}
              lastUpdatedAt={jobsLastUpdatedAt}
              onRefresh={() => loadJobs()}
            />
          ) : null}
        </div>
      </main>
    </div>
  );
}

export default App;
