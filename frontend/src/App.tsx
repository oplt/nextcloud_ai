import { useEffect, useMemo, useState } from 'react';

import {
  askChat,
  createConnector,
  getChatSession,
  getDocument,
  listChatSessions,
  listConnectors,
  listDocuments,
  listJobs,
  reindexDocument,
  syncConnector,
  testConnector,
} from './api/client';
import { useSession } from './hooks/useSession';
import { ChatPage } from './pages/ChatPage';
import { ConnectorsPage } from './pages/ConnectorsPage';
import { DocumentsPage } from './pages/DocumentsPage';
import { JobsPage } from './pages/JobsPage';
import { LoginPage } from './pages/LoginPage';
import { OverviewPage } from './pages/OverviewPage';
import type {
  ChatSessionDetail,
  ChatSessionSummary,
  ChatSource,
  Connector,
  ConnectorPayload,
  DocumentDetail,
  DocumentSummary,
  SyncJob,
} from './types/api';

type View = 'overview' | 'connectors' | 'documents' | 'jobs' | 'chat';

const navItems: Array<{ key: View; label: string }> = [
  { key: 'overview', label: 'Overview' },
  { key: 'connectors', label: 'Connectors' },
  { key: 'documents', label: 'Documents' },
  { key: 'jobs', label: 'Jobs' },
  { key: 'chat', label: 'Chat' },
];

function App() {
  const { user, loading, error, login, logout, refresh } = useSession();
  const [view, setView] = useState<View>('overview');
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [jobs, setJobs] = useState<SyncJob[]>([]);
  const [sessions, setSessions] = useState<ChatSessionSummary[]>([]);
  const [selectedDocument, setSelectedDocument] = useState<DocumentDetail | null>(null);
  const [selectedSession, setSelectedSession] = useState<ChatSessionDetail | null>(null);
  const [sources, setSources] = useState<ChatSource[]>([]);
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState<string | null>(null);

  const selectedDocumentId = selectedDocument?.id ?? null;

  const loadData = async () => {
    const [nextConnectors, nextDocuments, nextJobs, nextSessions] = await Promise.all([
      listConnectors(),
      listDocuments(),
      listJobs(),
      listChatSessions(),
    ]);
    setConnectors(nextConnectors);
    setDocuments(nextDocuments);
    setJobs(nextJobs);
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

  const currentTitle = useMemo(() => navItems.find((item) => item.key === view)?.label ?? 'Overview', [view]);

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
      const detail = await getChatSession(sessionId);
      setSelectedSession(detail);
      const assistantMessages = detail.messages.filter((message) => message.role === 'assistant');
      const lastAssistant = assistantMessages.at(-1);
      const citations = Array.isArray(lastAssistant?.citations_json) ? lastAssistant.citations_json : [];
      setSources(citations as ChatSource[]);
    }, 'Chat loaded');
  };

  const handleAsk = async (question: string) => {
    await withFeedback(async () => {
      const response = await askChat(question, selectedSession?.id);
      const detail = await getChatSession(response.session_id);
      setSelectedSession(detail);
      setSources(response.sources);
      setSessions(await listChatSessions());
    }, 'Grounded answer ready');
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

        {view === 'overview' ? <OverviewPage user={user} connectors={connectors} documents={documents} jobs={jobs} /> : null}
        {view === 'connectors' ? (
          <ConnectorsPage
            connectors={connectors}
            onCreate={handleCreateConnector}
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
        {view === 'jobs' ? <JobsPage jobs={jobs} connectors={connectors} /> : null}
        {view === 'chat' ? (
          <ChatPage
            sessions={sessions}
            activeSession={selectedSession}
            sources={sources}
            loading={busy}
            onSelectSession={handleSelectSession}
            onAsk={handleAsk}
          />
        ) : null}
      </main>
    </div>
  );
}

export default App;
