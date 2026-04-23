import type {
  AuditLog,
  AuditLogFilters,
  AuthSession,
  ChatAskRequest,
  ChatAskResponse,
  ChatMemoryPatchRequest,
  ChatSessionDetail,
  ChatSessionMemoryJson,
  ChatSessionSummary,
  Connector,
  ConnectorPayload,
  ConnectorUpdatePayload,
  CreateUserPayload,
  CsrfTokenResponse,
  DocumentDetail,
  DocumentListFilters,
  DocumentSummary,
  HealthReadiness,
  IntelligenceOverview,
  Role,
  SyncJob,
  UpdateUserPayload,
  User,
} from '../types/api';

const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api/v1').replace(/\/$/, '');
const AUTH_COOKIE_NAME = 'nc_ai_access_token';
const CSRF_COOKIE_NAME = 'nc_ai_csrf_token';
const CSRF_HEADER_NAME = 'X-CSRF-Token';
const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS']);

function isSafeMethod(method?: string): boolean {
  return SAFE_METHODS.has((method ?? 'GET').toUpperCase());
}

function readCookie(name: string): string | null {
  const prefix = `${name}=`;
  const cookies = document.cookie ? document.cookie.split('; ') : [];
  for (const cookie of cookies) {
    if (!cookie.startsWith(prefix)) {
      continue;
    }
    return decodeURIComponent(cookie.slice(prefix.length));
  }
  return null;
}

export function hasSessionCookie(): boolean {
  return readCookie(AUTH_COOKIE_NAME) !== null;
}

async function fetchCsrfToken(): Promise<string> {
  const response = await fetch(`${API_BASE}/auth/csrf`, {
    credentials: 'include',
  });

  if (!response.ok) {
    const message = await response.text().catch(() => `Request failed with ${response.status}`);
    throw new Error(message || `Request failed with ${response.status}`);
  }

  const payload = (await response.json()) as CsrfTokenResponse;
  if (typeof payload.csrf_token === 'string' && payload.csrf_token) {
    return payload.csrf_token;
  }

  const cookieToken = readCookie(CSRF_COOKIE_NAME);
  if (cookieToken) {
    return cookieToken;
  }

  throw new Error('CSRF token was not returned by the server');
}

export async function ensureCsrfToken(forceRefresh = false): Promise<string> {
  if (!forceRefresh) {
    const existing = readCookie(CSRF_COOKIE_NAME);
    if (existing) {
      return existing;
    }
  }
  return fetchCsrfToken();
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers ?? {});
  const method = (options.method ?? 'GET').toUpperCase();
  const hasFormData = options.body instanceof FormData;

  if (!hasFormData && !headers.has('Content-Type') && !isSafeMethod(method)) {
    headers.set('Content-Type', 'application/json');
  }
  if (!isSafeMethod(method)) {
    headers.set(CSRF_HEADER_NAME, await ensureCsrfToken());
  }

  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
    credentials: 'include',
  });

  if (response.status === 204) {
    return undefined as T;
  }

  if (!response.ok) {
    if (path === '/auth/me' && response.status === 401) {
      throw new Error('UNAUTHORIZED');
    }

    try {
      const payload = await response.json();
      if (typeof payload?.detail === 'string' && payload.detail) {
        throw new Error(payload.detail);
      }
      if (typeof payload?.message === 'string' && payload.message) {
        throw new Error(payload.message);
      }
      throw new Error(JSON.stringify(payload));
    } catch (jsonError) {
      if (jsonError instanceof Error && jsonError.message) {
        throw jsonError;
      }
      const message = await response.text().catch(() => `Request failed with ${response.status}`);
      throw new Error(message || `Request failed with ${response.status}`);
    }
  }

  return response.json() as Promise<T>;
}

export async function login(email: string, password: string): Promise<AuthSession> {
  return request<AuthSession>('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  });
}

export async function logout(): Promise<void> {
  await request<void>('/auth/logout', { method: 'POST' });
}

export async function getCurrentUser(): Promise<User> {
  return request<User>('/auth/me');
}

export async function getBackendReadiness(): Promise<HealthReadiness> {
  const response = await fetch(`${API_BASE}/health/ready`, {
    credentials: 'include',
  });

  let payload: HealthReadiness | null = null;
  try {
    payload = (await response.json()) as HealthReadiness;
  } catch {
    payload = null;
  }

  if (payload && (response.ok || response.status === 503)) {
    return payload;
  }

  if (!response.ok) {
    const detail =
      typeof payload === 'object' && payload && 'status' in payload
        ? `Health check failed: ${String(payload.status)}`
        : `Request failed with ${response.status}`;
    throw new Error(detail);
  }

  throw new Error('Health check returned an invalid payload');
}

export async function listConnectors(): Promise<Connector[]> {
  return request<Connector[]>('/connectors');
}

export async function createConnector(payload: ConnectorPayload): Promise<Connector> {
  return request<Connector>('/connectors', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function updateConnector(
  connectorId: string,
  payload: ConnectorUpdatePayload,
): Promise<Connector> {
  return request<Connector>(`/connectors/${connectorId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
}

export async function deleteConnector(connectorId: string): Promise<void> {
  return request<void>(`/connectors/${connectorId}`, {
    method: 'DELETE',
  });
}

export async function testConnector(connectorId: string): Promise<{ ok: boolean; message: string }> {
  return request<{ ok: boolean; message: string }>(`/connectors/${connectorId}/test`, { method: 'POST' });
}

export async function syncConnector(connectorId: string, fullReindex = false): Promise<SyncJob> {
  return request<SyncJob>(`/connectors/${connectorId}/sync`, {
    method: 'POST',
    body: JSON.stringify({ full_reindex: fullReindex }),
  });
}

export async function listDocuments(filters: DocumentListFilters = {}): Promise<DocumentSummary[]> {
  const params = new URLSearchParams();
  if (filters.query) {
    params.set('query', filters.query);
  }
  for (const connectorId of filters.connector_ids ?? []) {
    params.append('connector_id', connectorId);
  }
  for (const mimeType of filters.mime_types ?? []) {
    params.append('mime_type', mimeType);
  }
  for (const pathPrefix of filters.path_prefixes ?? []) {
    params.append('path_prefix', pathPrefix);
  }
  if (filters.modified_after) {
    params.set('modified_after', filters.modified_after);
  }
  if (filters.modified_before) {
    params.set('modified_before', filters.modified_before);
  }
  const suffix = params.toString();
  return request<DocumentSummary[]>(`/documents${suffix ? `?${suffix}` : ''}`);
}

export async function getDocument(documentId: string): Promise<DocumentDetail> {
  return request<DocumentDetail>(`/documents/${documentId}`);
}

export async function getIntelligenceOverview(): Promise<IntelligenceOverview> {
  return request<IntelligenceOverview>('/intelligence/overview');
}

export function getDocumentOriginalUrl(documentId: string): string {
  return `${API_BASE}/documents/${documentId}/original`;
}

export async function reindexDocument(documentId: string): Promise<{ status: string; task_id: string; document_id: string }> {
  return request<{ status: string; task_id: string; document_id: string }>(`/documents/${documentId}/reindex`, {
    method: 'POST',
  });
}

export async function listJobs(): Promise<SyncJob[]> {
  return request<SyncJob[]>('/jobs');
}

export async function retryJob(jobId: string): Promise<SyncJob> {
  return request<SyncJob>(`/jobs/${jobId}/retry`, {
    method: 'POST',
  });
}

export async function listChatSessions(): Promise<ChatSessionSummary[]> {
  return request<ChatSessionSummary[]>('/chat/sessions');
}

export async function getChatSession(sessionId: string): Promise<ChatSessionDetail> {
  return request<ChatSessionDetail>(`/chat/sessions/${sessionId}`);
}

export async function deleteChatSession(sessionId: string): Promise<void> {
  return request<void>(`/chat/sessions/${sessionId}`, {
    method: 'DELETE',
  });
}

export async function askChat(payload: ChatAskRequest): Promise<ChatAskResponse> {
  return request<ChatAskResponse>('/chat/ask', {
    method: 'POST',
    body: JSON.stringify({
      question: payload.question,
      session_id: payload.session_id ?? null,
      top_k: payload.top_k ?? 6,
      parent_message_id: payload.parent_message_id ?? null,
      document_ids: payload.document_ids ?? null,
      active_context_document_ids: payload.active_context_document_ids ?? [],
      request_id: payload.request_id ?? crypto.randomUUID(),
      retrieval_filters: payload.retrieval_filters ?? null,
      clear_session_memory: payload.clear_session_memory ?? false,
      focus_lock_document_ids: payload.focus_lock_document_ids ?? [],
      memory_items_patch: payload.memory_items_patch ?? null,
    }),
  });
}

export async function patchChatSessionMemory(
  sessionId: string,
  payload: ChatMemoryPatchRequest,
): Promise<ChatSessionMemoryJson> {
  return request<ChatSessionMemoryJson>(`/chat/sessions/${sessionId}/memory`, {
    method: 'PATCH',
    body: JSON.stringify({
      clear: payload.clear ?? false,
      focus_lock_document_ids: payload.focus_lock_document_ids ?? null,
      items: payload.items ?? [],
    }),
  });
}

export async function listUsers(query?: string): Promise<User[]> {
  const suffix = query ? `?query=${encodeURIComponent(query)}` : '';
  return request<User[]>(`/users/${suffix}`.replace('/?', '?'));
}

export async function createUser(payload: CreateUserPayload): Promise<User> {
  return request<User>('/users/', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function updateUser(userId: string, payload: UpdateUserPayload): Promise<User> {
  return request<User>(`/users/${userId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
}

export async function listRoles(): Promise<Role[]> {
  return request<Role[]>('/admin/roles');
}

export async function listAuditLogs(filters: AuditLogFilters = {}): Promise<AuditLog[]> {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value) {
      params.set(key, value);
    }
  }
  const suffix = params.toString();
  return request<AuditLog[]>(`/admin/audit-logs${suffix ? `?${suffix}` : ''}`);
}
