import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type Dispatch,
  type ReactNode,
  type SetStateAction,
} from 'react';
import { useLocation, useNavigate } from 'react-router-dom';

import {
  askChat,
  createConnector,
  createUser,
  deleteChatSession,
  deleteConnector,
  deleteUser,
  getChatSession,
  getBackendReadiness,
  getDocument,
  getIntelligenceOverview,
  listAuditLogs,
  listChatSessions,
  listConnectors,
  listDocuments,
  listJobs,
  listRoles,
  listUsers,
  reindexDocument,
  retryJob,
  syncConnector,
  testConnector,
  updateConnector,
  updateUser,
} from '../api/client';
import { useToast } from '../components/ui/ToastProvider';
import type {
  AuditLog,
  AuditLogFilters,
  ChatAskResponse,
  ChatMessage,
  ChatSessionDetail,
  ChatSessionSummary,
  Connector,
  ConnectorPayload,
  ConnectorUpdatePayload,
  DocumentDetail,
  DocumentSummary,
  IntelligenceOverview,
  RetrievalFilterFormState,
  Role,
  SyncJob,
  User,
} from '../types/api';

import {
  buildRetrievalFilters,
  createLocalChatMessage,
  EMPTY_CHAT_FILTERS,
  extractActiveContextDocumentIds,
  getLastAssistantMessageId,
  getUserInitials,
} from './chatHelpers';
import {
  buildWorkspaceNav,
  workspaceSectionFromPath,
  type WorkspaceNavItem,
  type WorkspaceSection,
} from './navConfig';

type BackendStatus = {
  kind: 'checking' | 'ready' | 'degraded' | 'offline';
  detail: string | null;
  checkedAt: string | null;
};

const HEALTH_POLL_INTERVAL_MS = 30_000;
const ACTIVE_JOBS_POLL_INTERVAL_MS = 5_000;
const IDLE_JOBS_POLL_INTERVAL_MS = 20_000;
const DOCUMENTS_POLL_INTERVAL_MS = 15_000;

function isActiveJob(job: SyncJob): boolean {
  return ['pending', 'queued', 'running', 'processing', 'retrying'].includes(job.status);
}

export type WorkspaceContextValue = {
  user: User;
  workspaceSection: WorkspaceSection;
  navigation: WorkspaceNavItem[];
  isAdmin: boolean;
  userInitials: string;
  busy: boolean;
  sessionRefreshing: boolean;
  workspaceRefreshing: boolean;
  backendStatus: BackendStatus;
  connectors: Connector[];
  documents: DocumentSummary[];
  jobs: SyncJob[];
  sessions: ChatSessionSummary[];
  users: User[];
  roles: Role[];
  auditLogs: AuditLog[];
  intelligenceOverview: IntelligenceOverview | null;
  selectedDocument: DocumentDetail | null;
  selectedDocumentId: string | null;
  activeSessionView: ChatSessionDetail | null;
  jobsLoading: boolean;
  jobsRefreshing: boolean;
  jobsError: string | null;
  jobsLastUpdatedAt: string | null;
  chatFilters: RetrievalFilterFormState;
  workspaceDataLoading: boolean;
  workspaceDataError: string | null;
  documentsViewLoading: boolean;
  documentsViewError: string | null;
  intelligenceLoading: boolean;
  intelligenceError: string | null;
  adminDataLoading: boolean;
  adminDataError: string | null;
  chatAskError: string | null;
  availableMimeTypes: string[];
  refresh: (options?: { silent?: boolean }) => Promise<void>;
  logout: () => Promise<void>;
  refreshWorkspace: () => Promise<void>;
  setChatFilters: Dispatch<SetStateAction<RetrievalFilterFormState>>;
  resetChatFilters: () => void;
  handleCreate: (payload: ConnectorPayload) => Promise<void>;
  handleUpdateConnector: (connectorId: string, payload: ConnectorUpdatePayload) => Promise<void>;
  handleDelete: (connectorId: string) => Promise<void>;
  handleTestConnector: (connectorId: string) => Promise<void>;
  handleSyncConnector: (connectorId: string, fullReindex?: boolean) => Promise<void>;
  handleToggleConnectorActive: (connectorId: string, nextActive: boolean) => Promise<void>;
  handleSelectDocument: (documentSummary: DocumentSummary) => Promise<void>;
  handleSelectDocumentById: (documentId: string) => Promise<void>;
  handleReindexDocument: (documentId: string) => Promise<void>;
  handleSelectSession: (sessionId: string) => Promise<void>;
  handleDeleteSessions: (ids: string[]) => Promise<void>;
  handleAsk: (question: string) => Promise<ChatAskResponse>;
  handleNewChat: () => void;
  handleRetryJob: (jobId: string) => Promise<void>;
  handleCreateUser: (payload: Parameters<typeof createUser>[0]) => Promise<void>;
  handleDeleteUsers: (userIds: string[]) => Promise<void>;
  handleUpdateUser: (
    userId: string,
    patch: { role_id?: string | null; is_active?: boolean },
  ) => Promise<void>;
  handleAssignConnectorOwner: (connectorId: string, ownerUserId: string | null) => Promise<void>;
  handleSearchAuditLogs: (filters: AuditLogFilters) => Promise<void>;
  loadAdminData: () => Promise<void>;
  loadJobs: (options?: { silent?: boolean }) => Promise<void>;
};

const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);

export function useWorkspace(): WorkspaceContextValue {
  const ctx = useContext(WorkspaceContext);
  if (!ctx) {
    throw new Error('useWorkspace must be used within WorkspaceProvider');
  }
  return ctx;
}

type WorkspaceProviderProps = {
  user: User;
  sessionRefreshing: boolean;
  refresh: (options?: { silent?: boolean }) => Promise<void>;
  sessionLogout: () => Promise<void>;
  children: ReactNode;
};

export function WorkspaceProvider({
  user,
  sessionRefreshing,
  refresh,
  sessionLogout,
  children,
}: WorkspaceProviderProps) {
  const location = useLocation();
  const navigate = useNavigate();
  const toast = useToast();
  const workspaceSection = useMemo(() => workspaceSectionFromPath(location.pathname), [location.pathname]);

  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [jobs, setJobs] = useState<SyncJob[]>([]);
  const [sessions, setSessions] = useState<ChatSessionSummary[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [roles, setRoles] = useState<Role[]>([]);
  const [auditLogs, setAuditLogs] = useState<AuditLog[]>([]);
  const [intelligenceOverview, setIntelligenceOverview] = useState<IntelligenceOverview | null>(null);
  const [selectedDocument, setSelectedDocument] = useState<DocumentDetail | null>(null);
  const [selectedSession, setSelectedSession] = useState<ChatSessionDetail | null>(null);
  const [pendingMessages, setPendingMessages] = useState<ChatMessage[]>([]);
  const [jobsLoading, setJobsLoading] = useState(false);
  const [jobsRefreshing, setJobsRefreshing] = useState(false);
  const [jobsError, setJobsError] = useState<string | null>(null);
  const [jobsLastUpdatedAt, setJobsLastUpdatedAt] = useState<string | null>(null);
  const [chatFilters, setChatFilters] = useState<RetrievalFilterFormState>(EMPTY_CHAT_FILTERS);

  const [workspaceDataLoading, setWorkspaceDataLoading] = useState(false);
  const [workspaceDataError, setWorkspaceDataError] = useState<string | null>(null);
  const [documentsViewLoading, setDocumentsViewLoading] = useState(false);
  const [documentsViewError, setDocumentsViewError] = useState<string | null>(null);
  const [intelligenceLoading, setIntelligenceLoading] = useState(false);
  const [intelligenceError, setIntelligenceError] = useState<string | null>(null);
  const [adminDataLoading, setAdminDataLoading] = useState(false);
  const [adminDataError, setAdminDataError] = useState<string | null>(null);
  const [workspaceRefreshing, setWorkspaceRefreshing] = useState(false);
  const [chatAskError, setChatAskError] = useState<string | null>(null);
  const [backendStatus, setBackendStatus] = useState<BackendStatus>({
    kind: 'checking',
    detail: null,
    checkedAt: null,
  });

  const [busy, setBusy] = useState(false);
  const latestChatRequestId = useRef<string | null>(null);
  const jobsRequestInFlight = useRef(false);

  const selectedDocumentId = selectedDocument?.id ?? null;
  const isAdmin = Boolean(user?.is_superuser || user?.role?.name === 'admin');
  const navigation = useMemo(() => buildWorkspaceNav(isAdmin), [isAdmin]);

  const availableMimeTypes = useMemo(
    () =>
      Array.from(new Set(documents.map((document) => document.mime_type).filter(Boolean) as string[])).sort(),
    [documents],
  );

  const activeSessionView = useMemo<ChatSessionDetail | null>(() => {
    if (selectedSession) {
      return pendingMessages.length === 0
        ? selectedSession
        : { ...selectedSession, messages: [...selectedSession.messages, ...pendingMessages] };
    }
    if (!user || pendingMessages.length === 0) return null;
    const first = pendingMessages[0];
    const last = pendingMessages[pendingMessages.length - 1];
    return {
      id: 'local-session',
      user_id: user.id,
      title: first.content.slice(0, 80) || 'New chat',
      created_at: first.created_at,
      updated_at: last.updated_at,
      messages: pendingMessages,
    };
  }, [pendingMessages, selectedSession, user]);

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
    } catch (cause) {
      setJobsError(cause instanceof Error ? cause.message : 'Failed to load jobs');
    } finally {
      jobsRequestInFlight.current = false;
      if (silent) {
        setJobsRefreshing(false);
      } else {
        setJobsLoading(false);
      }
    }
  }, []);

  const loadAdminData = useCallback(async () => {
    const [nextUsers, nextRoles, nextAuditLogs] = await Promise.all([
      listUsers(),
      listRoles(),
      listAuditLogs(),
    ]);
    setUsers(nextUsers);
    setRoles(nextRoles);
    setAuditLogs(nextAuditLogs);
  }, []);

  const loadAuditLogSnapshot = useCallback(async (filters: AuditLogFilters = {}) => {
    setAuditLogs(await listAuditLogs(filters));
  }, []);

  const loadIntelligenceData = useCallback(async () => {
    const data = await getIntelligenceOverview();
    setIntelligenceOverview(data);
  }, []);

  const refreshDocumentsView = useCallback(
    async (options?: { silent?: boolean }) => {
      const silent = options?.silent ?? false;
      if (!silent) {
        setDocumentsViewLoading(true);
      }
      try {
        await Promise.all([loadDocuments(), loadConnectors()]);
        setDocumentsViewError(null);
      } catch (cause) {
        const message = cause instanceof Error ? cause.message : 'Failed to load documents';
        setDocumentsViewError(message);
        if (!silent) {
          toast.push({ message, severity: 'error' });
        }
      } finally {
        if (!silent) {
          setDocumentsViewLoading(false);
        }
      }
    },
    [loadConnectors, loadDocuments, toast],
  );

  const loadData = useCallback(async () => {
    const [nextConnectors, nextDocuments, nextSessions] = await Promise.all([
      listConnectors(),
      listDocuments(),
      listChatSessions(),
    ]);
    setConnectors(nextConnectors);
    setDocuments(nextDocuments);
    setSessions(nextSessions);
  }, []);

  const checkBackendStatus = useCallback(async () => {
    try {
      const readiness = await getBackendReadiness();
      const problems = [
        readiness.status !== 'ready' ? `status:${readiness.status}` : null,
        readiness.database !== 'ok' ? `db:${readiness.database}` : null,
        readiness.redis !== 'ok' ? `redis:${readiness.redis}` : null,
        readiness.broker !== 'ok' ? `broker:${readiness.broker}` : null,
        readiness.ai_runtime.ready ? null : readiness.ai_runtime.error || 'ai:not_ready',
      ].filter(Boolean);

      setBackendStatus({
        kind: problems.length === 0 ? 'ready' : 'degraded',
        detail: problems.length === 0 ? null : problems.join(' | '),
        checkedAt: new Date().toISOString(),
      });
    } catch (cause) {
      setBackendStatus({
        kind: 'offline',
        detail: cause instanceof Error ? cause.message : 'Server unreachable',
        checkedAt: new Date().toISOString(),
      });
    }
  }, []);

  useEffect(() => {
    if (!user) {
      setWorkspaceDataError(null);
      setWorkspaceDataLoading(false);
      return;
    }
    let cancelled = false;
    setWorkspaceDataLoading(true);
    setWorkspaceDataError(null);
    void loadData()
      .then(() => {
        if (!cancelled) {
          setWorkspaceDataLoading(false);
        }
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          setWorkspaceDataLoading(false);
          setWorkspaceDataError(cause instanceof Error ? cause.message : 'Failed to load dashboard data');
        }
      });
    return () => {
      cancelled = true;
    };
  }, [loadData, user]);

  useEffect(() => {
    if (!user) {
      setBackendStatus({ kind: 'checking', detail: null, checkedAt: null });
      return;
    }

    let disposed = false;
    const runCheck = async () => {
      try {
        const readiness = await getBackendReadiness();
        if (disposed) {
          return;
        }
        const problems = [
          readiness.status !== 'ready' ? `status:${readiness.status}` : null,
          readiness.database !== 'ok' ? `db:${readiness.database}` : null,
          readiness.redis !== 'ok' ? `redis:${readiness.redis}` : null,
          readiness.broker !== 'ok' ? `broker:${readiness.broker}` : null,
          readiness.ai_runtime.ready ? null : readiness.ai_runtime.error || 'ai:not_ready',
        ].filter(Boolean);

        setBackendStatus({
          kind: problems.length === 0 ? 'ready' : 'degraded',
          detail: problems.length === 0 ? null : problems.join(' | '),
          checkedAt: new Date().toISOString(),
        });
      } catch (cause) {
        if (disposed) {
          return;
        }
        setBackendStatus({
          kind: 'offline',
          detail: cause instanceof Error ? cause.message : 'Server unreachable',
          checkedAt: new Date().toISOString(),
        });
      }
    };

    void runCheck();
    const intervalId = window.setInterval(() => {
      if (document.visibilityState !== 'hidden') {
        void runCheck();
      }
    }, HEALTH_POLL_INTERVAL_MS);

    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        void runCheck();
      }
    };

    const handleFocus = () => {
      void runCheck();
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);
    window.addEventListener('focus', handleFocus);

    return () => {
      disposed = true;
      window.clearInterval(intervalId);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
      window.removeEventListener('focus', handleFocus);
    };
  }, [user]);

  useEffect(() => {
    if (!user || workspaceSection !== 'jobs') {
      return;
    }

    const jobsPollIntervalMs = jobs.some(isActiveJob)
      ? ACTIVE_JOBS_POLL_INTERVAL_MS
      : IDLE_JOBS_POLL_INTERVAL_MS;

    void loadJobs({ silent: jobs.length > 0 });
    const intervalId = window.setInterval(() => {
      if (document.visibilityState !== 'hidden') {
        void loadJobs({ silent: true });
      }
    }, jobsPollIntervalMs);

    return () => {
      window.clearInterval(intervalId);
    };
  }, [jobs, loadJobs, user, workspaceSection]);

  useEffect(() => {
    if (!user || workspaceSection !== 'documents') {
      return;
    }

    void refreshDocumentsView();
    const intervalId = window.setInterval(() => {
      if (document.visibilityState !== 'hidden') {
        void refreshDocumentsView({ silent: true });
      }
    }, DOCUMENTS_POLL_INTERVAL_MS);

    return () => {
      window.clearInterval(intervalId);
    };
  }, [refreshDocumentsView, user, workspaceSection]);

  useEffect(() => {
    if (!user || !isAdmin || workspaceSection !== 'admin') {
      return;
    }
    let cancelled = false;
    setAdminDataLoading(true);
    setAdminDataError(null);
    void loadAdminData()
      .then(() => {
        if (!cancelled) {
          setAdminDataLoading(false);
        }
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          setAdminDataLoading(false);
          setAdminDataError(cause instanceof Error ? cause.message : 'Failed to load admin data');
        }
      });
    return () => {
      cancelled = true;
    };
  }, [isAdmin, loadAdminData, user, workspaceSection]);

  useEffect(() => {
    if (!user || workspaceSection !== 'intelligence') {
      return;
    }
    let cancelled = false;
    setIntelligenceLoading(true);
    setIntelligenceError(null);
    void loadIntelligenceData()
      .then(() => {
        if (!cancelled) {
          setIntelligenceLoading(false);
        }
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          setIntelligenceLoading(false);
          setIntelligenceError(cause instanceof Error ? cause.message : 'Failed to load intelligence data');
        }
      });
    return () => {
      cancelled = true;
    };
  }, [loadIntelligenceData, user, workspaceSection]);

  const withFeedback = useCallback(
    async (work: () => Promise<void>, successMessage: string) => {
      setBusy(true);
      try {
        await work();
        toast.push({ message: successMessage, severity: 'success' });
      } catch (cause) {
        toast.push({
          message: cause instanceof Error ? cause.message : 'Operation failed',
          severity: 'error',
        });
      } finally {
        setBusy(false);
      }
    },
    [toast],
  );

  const handleCreate = useCallback(
    async (payload: ConnectorPayload) => {
      await withFeedback(async () => {
        await createConnector(payload);
        await loadConnectors();
      }, 'Connector saved');
    },
    [loadConnectors, withFeedback],
  );

  const handleUpdateConnector = useCallback(
    async (connectorId: string, payload: ConnectorUpdatePayload) => {
      await withFeedback(async () => {
        await updateConnector(connectorId, payload);
        await loadConnectors();
      }, 'Connector updated');
    },
    [loadConnectors, withFeedback],
  );

  const handleDelete = useCallback(
    async (connectorId: string) => {
      await withFeedback(async () => {
        await deleteConnector(connectorId);
        if (selectedDocument?.connector_id === connectorId) {
          setSelectedDocument(null);
        }
        await Promise.all([loadConnectors(), loadDocuments()]);
      }, 'Connector deleted');
    },
    [loadConnectors, loadDocuments, selectedDocument, withFeedback],
  );

  const handleTestConnector = useCallback(
    async (connectorId: string) => {
      await withFeedback(async () => {
        await testConnector(connectorId);
        await loadConnectors();
      }, 'Connector test passed');
    },
    [loadConnectors, withFeedback],
  );

  const handleSyncConnector = useCallback(
    async (connectorId: string, fullReindex = false) => {
      await withFeedback(async () => {
        await syncConnector(connectorId, fullReindex);
        await Promise.all([loadConnectors(), loadJobs({ silent: true })]);
      }, fullReindex ? 'Full reindex queued' : 'Sync queued');
    },
    [loadConnectors, loadJobs, withFeedback],
  );

  const handleToggleConnectorActive = useCallback(
    async (connectorId: string, nextActive: boolean) => {
      await withFeedback(async () => {
        await updateConnector(connectorId, { is_active: nextActive });
        await loadConnectors();
      }, nextActive ? 'Connector activated' : 'Connector deactivated');
    },
    [loadConnectors, withFeedback],
  );

  const handleSelectDocument = useCallback(
    async (documentSummary: DocumentSummary) => {
      await withFeedback(async () => {
        const detail = await getDocument(documentSummary.id);
        setSelectedDocument(detail);
      }, `Loaded ${documentSummary.file_name}`);
    },
    [withFeedback],
  );

  const handleSelectDocumentById = useCallback(
    async (documentId: string) => {
      await withFeedback(async () => {
        const detail = await getDocument(documentId);
        setSelectedDocument(detail);
      }, 'Loaded structured document detail');
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
    [loadData, loadJobs, withFeedback],
  );

  const handleSelectSession = useCallback(
    async (sessionId: string) => {
      await withFeedback(async () => {
        setPendingMessages([]);
        setChatAskError(null);
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
        setSessions((current) => current.filter((session) => !ids.includes(session.id)));
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
    async (question: string): Promise<ChatAskResponse> => {
      const requestId = crypto.randomUUID();
      latestChatRequestId.current = requestId;

      const sessionId = selectedSession?.id ?? null;
      const currentMessages = activeSessionView?.messages ?? [];
      const parentMessageId = getLastAssistantMessageId(currentMessages);
      const contextDocumentIds = [
        ...new Set([
          ...extractActiveContextDocumentIds(currentMessages),
        ]),
      ];
      const optimisticMessage = createLocalChatMessage('user', question, sessionId);

      setBusy(true);
      
      setChatAskError(null);
      setPendingMessages((current) => [...current, optimisticMessage]);

      try {
        const response = await askChat({
          question,
          session_id: sessionId,
          parent_message_id: parentMessageId,
          active_context_document_ids: contextDocumentIds,
          request_id: requestId,
          top_k: 6,
          retrieval_filters: buildRetrievalFilters(chatFilters),
        });

        if (latestChatRequestId.current !== requestId) {
          return response;
        }

        try {
          const [detail, nextSessions] = await Promise.all([
            getChatSession(response.session_id),
            listChatSessions(),
          ]);
          setSelectedSession(detail);
          setSessions(nextSessions);
          setPendingMessages([]);
        } catch (refreshError) {
          const message = refreshError instanceof Error ? refreshError.message : 'Failed to reload chat';
          toast.push({ message: `Chat saved, but history refresh failed: ${message}`, severity: 'error' });
          setPendingMessages([
            optimisticMessage,
            createLocalChatMessage('assistant', response.answer, response.session_id),
          ]);
        }

        return response;
      } catch (cause) {
        const message = cause instanceof Error ? cause.message : 'Chat request failed';
        setChatAskError(message);
        toast.push({ message, severity: 'error' });
        setPendingMessages([
          optimisticMessage,
          createLocalChatMessage('assistant', `I could not complete this request: ${message}`, sessionId),
        ]);
        throw cause instanceof Error ? cause : new Error(message);
      } finally {
        if (latestChatRequestId.current === requestId) {
          setBusy(false);
        }
      }
    },
    [activeSessionView, chatFilters, selectedSession, toast],
  );

  const handleNewChat = useCallback(() => {
    setSelectedSession(null);
    setPendingMessages([]);
    
    setChatAskError(null);
    latestChatRequestId.current = null;
  }, []);

  const handleRetryJob = useCallback(
    async (jobId: string) => {
      await withFeedback(async () => {
        await retryJob(jobId);
        await loadJobs();
      }, 'Retry queued');
    },
    [loadJobs, withFeedback],
  );

  const handleCreateUser = useCallback(
    async (payload: Parameters<typeof createUser>[0]) => {
      await withFeedback(async () => {
        await createUser(payload);
        await loadAdminData();
      }, 'User created');
    },
    [loadAdminData, withFeedback],
  );

  const handleDeleteUsers = useCallback(
    async (userIds: string[]) => {
      await withFeedback(async () => {
        await Promise.all(userIds.map((userId) => deleteUser(userId)));
        await loadAdminData();
      }, userIds.length === 1 ? 'User deleted' : `${userIds.length} users deleted`);
    },
    [loadAdminData, withFeedback],
  );

  const handleUpdateUser = useCallback(
    async (userId: string, patch: { role_id?: string | null; is_active?: boolean }) => {
      await withFeedback(async () => {
        await updateUser(userId, patch);
        await loadAdminData();
      }, 'User updated');
    },
    [loadAdminData, withFeedback],
  );

  const handleAssignConnectorOwner = useCallback(
    async (connectorId: string, ownerUserId: string | null) => {
      await withFeedback(async () => {
        await updateConnector(connectorId, { owner_user_id: ownerUserId });
        await Promise.all([loadConnectors(), loadAdminData()]);
      }, 'Connector ownership updated');
    },
    [loadAdminData, loadConnectors, withFeedback],
  );

  const handleSearchAuditLogs = useCallback(
    async (filters: AuditLogFilters) => {
      await withFeedback(async () => {
        await loadAuditLogSnapshot(filters);
      }, 'Audit log filters applied');
    },
    [loadAuditLogSnapshot, withFeedback],
  );

  const handleRefreshWorkspace = useCallback(async () => {
    setWorkspaceRefreshing(true);
    
    setWorkspaceDataError(null);
    setDocumentsViewError(null);
    setIntelligenceError(null);
    setAdminDataError(null);
    try {
      await refresh({ silent: true });
      await loadData();
      await checkBackendStatus();
      if (workspaceSection === 'jobs') {
        await loadJobs();
      }
      if (workspaceSection === 'intelligence') {
        await loadIntelligenceData();
      }
      if (workspaceSection === 'admin' && isAdmin) {
        await loadAdminData();
      }
      if (workspaceSection === 'documents') {
        await refreshDocumentsView();
      }
      toast.push({ message: 'Workspace refreshed', severity: 'success' });
    } catch (cause: unknown) {
      toast.push({ message: cause instanceof Error ? cause.message : 'Refresh failed', severity: 'error' });
    } finally {
      setWorkspaceRefreshing(false);
    }
  }, [checkBackendStatus, isAdmin, loadAdminData, loadData, loadIntelligenceData, loadJobs, refresh, refreshDocumentsView, workspaceSection, toast]);

  const handleLogout = useCallback(async () => {
    setBusy(true);
    
    try {
      await sessionLogout();
      navigate('/');
      setConnectors([]);
      setDocuments([]);
      setJobs([]);
      setSessions([]);
      setUsers([]);
      setRoles([]);
      setAuditLogs([]);
      setIntelligenceOverview(null);
      setSelectedDocument(null);
      setSelectedSession(null);
      setPendingMessages([]);
      setJobsLoading(false);
      setJobsRefreshing(false);
      setJobsError(null);
      setJobsLastUpdatedAt(null);
      setChatFilters(EMPTY_CHAT_FILTERS);
      setWorkspaceDataLoading(false);
      setWorkspaceDataError(null);
      setDocumentsViewLoading(false);
      setDocumentsViewError(null);
      setIntelligenceLoading(false);
      setIntelligenceError(null);
      setAdminDataLoading(false);
      setAdminDataError(null);
      setWorkspaceRefreshing(false);
      setChatAskError(null);
      latestChatRequestId.current = null;
      jobsRequestInFlight.current = false;
    } catch (cause) {
      toast.push({ message: cause instanceof Error ? cause.message : 'Sign out failed', severity: 'error' });
    } finally {
      setBusy(false);
    }
  }, [sessionLogout, navigate, toast]);


  const userInitials = useMemo(() => getUserInitials(user.full_name ?? user.username), [user]);

  const resetChatFilters = useCallback(() => {
    setChatFilters(EMPTY_CHAT_FILTERS);
  }, []);

  const value: WorkspaceContextValue = {
    user,
    workspaceSection,
    navigation,
    isAdmin,
    userInitials,
    busy,
    sessionRefreshing,
    workspaceRefreshing,
    backendStatus,
    connectors,
    documents,
    jobs,
    sessions,
    users,
    roles,
    auditLogs,
    intelligenceOverview,
    selectedDocument,
    selectedDocumentId,
    activeSessionView,
    jobsLoading,
    jobsRefreshing,
    jobsError,
    jobsLastUpdatedAt,
    chatFilters,
    workspaceDataLoading,
    workspaceDataError,
    documentsViewLoading,
    documentsViewError,
    intelligenceLoading,
    intelligenceError,
    adminDataLoading,
    adminDataError,
    chatAskError,
    availableMimeTypes,
    refresh,
    logout: handleLogout,
    refreshWorkspace: handleRefreshWorkspace,
    setChatFilters,
    resetChatFilters,
    handleCreate,
    handleUpdateConnector,
    handleDelete,
    handleTestConnector,
    handleSyncConnector,
    handleToggleConnectorActive,
    handleSelectDocument,
    handleSelectDocumentById,
    handleReindexDocument,
    handleSelectSession,
    handleDeleteSessions,
    handleAsk,
    handleNewChat,
    handleRetryJob,
    handleCreateUser,
    handleDeleteUsers,
    handleUpdateUser,
    handleAssignConnectorOwner,
    handleSearchAuditLogs,
    loadAdminData,
    loadJobs,
  };

  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}
