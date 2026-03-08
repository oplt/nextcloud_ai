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

const navItems: Array<{ key: View; label: string }> = [
  { key: 'overview', label: 'Home' },
  { key: 'connectors', label: 'Connectors' },
  { key: 'documents', label: 'Documents' },
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

  const currentTitle = useMemo(() => navItems.find((item) => item.key === view)?.label ?? 'Home', [view]);

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

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div>
          <p className="eyebrow">MVP Control Plane</p>
          <h1>Nextcloud AI</h1>
        </div>
        <nav>
          {navItems.map((item) => (
            <button
              key={item.key}
              type="button"
              className={item.key === view ? 'nav-button nav-button--active' : 'nav-button'}
              onClick={() => setView(item.key)}
            >
              {item.label}
            </button>
          ))}
        </nav>
        <footer className="sidebar-footer">
          <p>{user.full_name ?? user.username}</p>
          <small>{user.email ?? user.external_subject}</small>
          <div className="sidebar-actions">
            <button type="button" onClick={() => void refresh()}>
              Refresh Session
            </button>
            <button type="button" onClick={() => void logout()}>
              Logout
            </button>
          </div>
        </footer>
      </aside>
      <main className="main-shell">
        <header className="main-header">
          <div>
            <p className="eyebrow">{currentTitle}</p>
            <h2>Private company knowledge workspace</h2>
          </div>
          {flash ? <p className="flash-banner">{flash}</p> : null}
        </header>

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
      </main>
    </div>
  );
}

export default App;
