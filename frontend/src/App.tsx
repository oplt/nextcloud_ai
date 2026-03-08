import { useEffect, useMemo, useState } from 'react';

import {
  askChat,
  createConnector,
  deleteConnector,
  getChatSession,
  getDocument,
  listChatSessions,
  listConnectors,
  listDocuments,
  reindexDocument,
  syncConnector,
  testConnector,
} from './api/client';
import { useSession } from './hooks/useSession';
import { ConnectorsPage } from './pages/ConnectorsPage';
import { DocumentsPage } from './pages/DocumentsPage';
import { LoginPage } from './pages/LoginPage';
import { OverviewPage } from './pages/OverviewPage';
import type {
  ChatMessage,
  ChatSessionDetail,
  ChatSessionSummary,
  ChatSource,
  Connector,
  ConnectorPayload,
  DocumentDetail,
  DocumentSummary,
} from './types/api';

type View = 'overview' | 'connectors' | 'documents';

const navItems: Array<{ key: View; label: string; heading: string; description: string }> = [
  {
    key: 'overview',
    label: 'Home',
    heading: 'Private company knowledge workspace',
    description: 'Track connector health, browse synced content, and work with the latest chat context.',
  },
  {
    key: 'connectors',
    label: 'Connectors',
    heading: 'Connector management',
    description: 'Configure Nextcloud sources, validate credentials, and run sync jobs from one place.',
  },
  {
    key: 'documents',
    label: 'Documents',
    heading: 'Document catalog',
    description: 'Review indexed files, inspect metadata, and requeue document parsing when needed.',
  },
];

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

function getUserInitials(name: string | null | undefined): string {
  const parts = name?.trim().split(/\s+/).filter(Boolean) ?? [];
  if (parts.length === 0) {
    return 'NC';
  }

  return parts
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? '')
    .join('');
}

function App() {
  const { user, loading, error, login, logout, refresh } = useSession();
  const [view, setView] = useState<View>('overview');
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [sessions, setSessions] = useState<ChatSessionSummary[]>([]);
  const [selectedDocument, setSelectedDocument] = useState<DocumentDetail | null>(null);
  const [selectedSession, setSelectedSession] = useState<ChatSessionDetail | null>(null);
  const [sources, setSources] = useState<ChatSource[]>([]);
  const [pendingMessages, setPendingMessages] = useState<ChatMessage[]>([]);
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState<string | null>(null);

  const selectedDocumentId = selectedDocument?.id ?? null;
  const activeSessionView = useMemo<ChatSessionDetail | null>(() => {
    if (selectedSession) {
      return pendingMessages.length === 0
        ? selectedSession
        : { ...selectedSession, messages: [...selectedSession.messages, ...pendingMessages] };
    }
    if (!user || pendingMessages.length === 0) {
      return null;
    }

    const firstMessage = pendingMessages[0];
    const lastMessage = pendingMessages[pendingMessages.length - 1];
    return {
      id: 'local-session',
      user_id: user.id,
      title: firstMessage.content.slice(0, 80) || 'New chat',
      created_at: firstMessage.created_at,
      updated_at: lastMessage.updated_at,
      messages: pendingMessages,
    };
  }, [pendingMessages, selectedSession, user]);

  const loadData = async () => {
    const [nextConnectors, nextDocuments, nextSessions] = await Promise.all([
      listConnectors(),
      listDocuments(),
      listChatSessions(),
    ]);
    setConnectors(nextConnectors);
    setDocuments(nextDocuments);
    setSessions(nextSessions);
  };

  useEffect(() => {
    if (!user) {
      return;
    }
    void loadData().catch((loadError: unknown) => {
      setFlash(loadError instanceof Error ? loadError.message : 'Failed to load dashboard data');
    });
  }, [user]);

  const currentView = useMemo(
    () => navItems.find((item) => item.key === view) ?? navItems[0],
    [view],
  );

  const withFeedback = async (work: () => Promise<void>, successMessage: string) => {
    setBusy(true);
    setFlash(null);
    try {
      await work();
      setFlash(successMessage);
    } catch (workError) {
      setFlash(workError instanceof Error ? workError.message : 'Operation failed');
    } finally {
      setBusy(false);
    }
  };

  const handleCreateConnector = async (payload: ConnectorPayload) => {
    await withFeedback(async () => {
      await createConnector(payload);
      await loadData();
    }, 'Connector saved');
  };

  const handleDeleteConnector = async (connectorId: string) => {
    await withFeedback(async () => {
      await deleteConnector(connectorId);
      if (selectedDocument?.connector_id === connectorId) {
        setSelectedDocument(null);
      }
      await loadData();
    }, 'Connector deleted');
  };

  const handleSelectDocument = async (document: DocumentSummary) => {
    await withFeedback(async () => {
      const detail = await getDocument(document.id);
      setSelectedDocument(detail);
    }, `Loaded ${document.file_name}`);
  };

  const handleReindexDocument = async (documentId: string) => {
    await withFeedback(async () => {
      await reindexDocument(documentId);
      await loadData();
    }, 'Document reindex queued');
  };

  const handleSelectSession = async (sessionId: string) => {
    await withFeedback(async () => {
      setPendingMessages([]);
      const detail = await getChatSession(sessionId);
      setSelectedSession(detail);
      const assistantMessages = detail.messages.filter((message) => message.role === 'assistant');
      const lastAssistant = assistantMessages.at(-1);
      const citations = Array.isArray(lastAssistant?.citations_json) ? lastAssistant.citations_json : [];
      setSources(citations as ChatSource[]);
    }, 'Chat loaded');
  };

  const handleAsk = async (question: string) => {
    const sessionId = selectedSession?.id ?? null;
    const optimisticUserMessage = createLocalChatMessage('user', question, sessionId);

    setBusy(true);
    setFlash(null);
    setSources([]);
    setPendingMessages([optimisticUserMessage]);

    try {
      const response = await askChat(question, selectedSession?.id);
      setSources(response.sources);
      try {
        const [detail, nextSessions] = await Promise.all([
          getChatSession(response.session_id),
          listChatSessions(),
        ]);
        setSelectedSession(detail);
        setSessions(nextSessions);
        setPendingMessages([]);
      } catch (refreshError) {
        const message =
          refreshError instanceof Error ? refreshError.message : 'Failed to reload chat history';
        setFlash(`Chat saved, but the history refresh failed: ${message}`);
        setPendingMessages([
          optimisticUserMessage,
          createLocalChatMessage('assistant', response.answer, response.session_id),
        ]);
      }
    } catch (workError) {
      const message = workError instanceof Error ? workError.message : 'Chat request failed';
      setFlash(message);
      setPendingMessages([
        optimisticUserMessage,
        createLocalChatMessage(
          'assistant',
          `I could not complete this request: ${message}`,
          sessionId,
        ),
      ]);
      throw workError instanceof Error ? workError : new Error(message);
    } finally {
      setBusy(false);
    }
  };

  const handleNewChat = () => {
    setSelectedSession(null);
    setPendingMessages([]);
    setSources([]);
    setFlash(null);
  };

  if (loading) {
    return <div className="app-loading">Loading workspace…</div>;
  }

  if (!user) {
    return <LoginPage onLogin={login} error={error} />;
  }

  const userLabel = user.full_name ?? user.username;
  const userMeta = user.email ?? user.external_subject ?? 'Authenticated session';

  return (
    <div className="app-shell">
      <header className="top-nav">
        <div className="nav-brand">
          <div className="nav-brand-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" role="presentation">
              <path
                fill="currentColor"
                d="M18.5 18a3.5 3.5 0 0 0 .72-6.93A6 6 0 0 0 7.3 9.3 4.5 4.5 0 0 0 6 18h12.5Zm-12.43-2a2.5 2.5 0 1 1 .6-4.93l1.23.3.22-1.25a4 4 0 0 1 7.93.55v1h.75a1.5 1.5 0 1 1 0 3H6.07Z"
              />
            </svg>
          </div>
          <div className="nav-brand-name">
            Nextcloud <span className="accent">AI</span>
          </div>
        </div>
        <nav className="nav-links" aria-label="Primary">
          {navItems.map((item) => (
            <button
              key={item.key}
              type="button"
              className={item.key === view ? 'nav-link active' : 'nav-link'}
              aria-current={item.key === view ? 'page' : undefined}
              onClick={() => setView(item.key)}
            >
              {item.label}
            </button>
          ))}
        </nav>
        <div className="nav-end">
          <button type="button" className="btn" onClick={() => void refresh()}>
            Refresh Session
          </button>
          <div className="nav-avatar" title={userLabel}>
            {getUserInitials(userLabel)}
          </div>
          <button type="button" className="nav-link nav-link--logout" onClick={() => void logout()}>
            Logout
          </button>
        </div>
      </header>
      <main className="page-content">
        <div className="page-body">
          <header className="page-header">
            <div>
              <p className="page-kicker">{currentView.label}</p>
              <h1>{currentView.heading}</h1>
              <p className="page-description">{currentView.description}</p>
            </div>
            <div className="page-header-meta">
              <strong>{userLabel}</strong>
              <span>{userMeta}</span>
            </div>
          </header>
          <div>
            {flash ? <p className="flash-banner">{flash}</p> : null}
          </div>

          {view === 'overview' ? (
            <OverviewPage
              user={user}
              connectors={connectors}
              documents={documents}
              sessions={sessions}
              activeSession={activeSessionView}
              sources={sources}
              loading={busy}
              onSelectSession={handleSelectSession}
              onAsk={handleAsk}
              onNewChat={handleNewChat}
            />
          ) : null}
          {view === 'connectors' ? (
            <ConnectorsPage
              connectors={connectors}
              onCreate={handleCreateConnector}
              onDelete={handleDeleteConnector}
              onTest={(connectorId) => withFeedback(async () => {
                const result = await testConnector(connectorId);
                setFlash(result.message);
              }, 'Connector validated')}
              onSync={(connectorId, fullReindex) => withFeedback(async () => {
                await syncConnector(connectorId, Boolean(fullReindex));
                await loadData();
              }, fullReindex ? 'Full reindex queued' : 'Sync queued')}
            />
          ) : null}
          {view === 'documents' ? (
            <DocumentsPage
              documents={documents}
              selectedDocumentId={selectedDocumentId}
              selectedDocument={selectedDocument}
              onSelect={handleSelectDocument}
              onReindex={handleReindexDocument}
            />
          ) : null}
        </div>
      </main>
    </div>
  );
}

export default App;
