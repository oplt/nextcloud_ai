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
  DocumentListResponse,
  DocumentListFilters,
  DocumentSummary,
  HealthReadiness,
  IntelligenceOverview,
  Role,
  SyncJobListResponse,
  SyncJob,
  UpdateUserPayload,
  User,
} from '../types/api';

const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api/v1').replace(/\/$/, '');
const AUTH_COOKIE_NAME = 'nc_ai_access_token';
const CSRF_COOKIE_NAME = 'nc_ai_csrf_token';
const CSRF_HEADER_NAME = 'X-CSRF-Token';
const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS']);
const GET_CACHE = new Map<string, { expiresAt: number; value: unknown }>();
const GET_IN_FLIGHT = new Map<string, Promise<unknown>>();

type ApiValidationIssue = {
  type?: string;
  loc?: Array<string | number>;
  msg?: string;
  ctx?: Record<string, unknown>;
};

function isSafeMethod(method?: string): boolean {
  return SAFE_METHODS.has((method ?? 'GET').toUpperCase());
}

function formatFieldName(loc: ApiValidationIssue['loc']): string {
  const raw = loc?.filter((part) => part !== 'body').at(-1);
  if (typeof raw !== 'string' || raw.length === 0) {
    return 'This field';
  }
  return raw
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatValidationIssue(issue: ApiValidationIssue): string {
  const field = formatFieldName(issue.loc);
  const minLength = issue.ctx?.min_length;
  if (issue.type === 'string_too_short' && typeof minLength === 'number') {
    return `${field} must be at least ${minLength} characters.`;
  }
  if (issue.type?.includes('email')) {
    return `${field} must be a valid email address.`;
  }
  return `${field}: ${issue.msg ?? 'Invalid value.'}`;
}

function formatApiError(payload: unknown, fallback: string): string {
  if (!payload || typeof payload !== 'object') {
    return fallback;
  }
  const data = payload as { detail?: unknown; message?: unknown };
  if (typeof data.detail === 'string' && data.detail) {
    return data.detail;
  }
  if (Array.isArray(data.detail) && data.detail.length > 0) {
    return data.detail
      .map((issue) => formatValidationIssue(issue as ApiValidationIssue))
      .join(' ');
  }
  if (typeof data.message === 'string' && data.message) {
    return data.message;
  }
  return fallback;
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

async function cachedGet<T>(
  key: string,
  ttlMs: number,
  loader: () => Promise<T>,
): Promise<T> {
  const now = Date.now();
  const cached = GET_CACHE.get(key);
  if (cached && cached.expiresAt > now) {
    return cached.value as T;
  }
  const pending = GET_IN_FLIGHT.get(key);
  if (pending) {
    return pending as Promise<T>;
  }
  const promise = loader()
    .then((value) => {
      GET_CACHE.set(key, { value, expiresAt: Date.now() + ttlMs });
      return value;
    })
    .finally(() => {
      GET_IN_FLIGHT.delete(key);
    });
  GET_IN_FLIGHT.set(key, promise);
  return promise;
}

function invalidateGetCache(prefixes: string[] = []): void {
  if (prefixes.length === 0) {
    GET_CACHE.clear();
    return;
  }
  for (const key of Array.from(GET_CACHE.keys())) {
    if (prefixes.some((prefix) => key.startsWith(prefix))) {
      GET_CACHE.delete(key);
    }
  }
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
      throw new Error(formatApiError(payload, `Request failed with ${response.status}`));
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
  const connector = await request<Connector>('/connectors', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  invalidateGetCache(['/connectors', '/documents', '/jobs', '/intelligence']);
  return connector;
}

export async function updateConnector(
  connectorId: string,
  payload: ConnectorUpdatePayload,
): Promise<Connector> {
  const connector = await request<Connector>(`/connectors/${connectorId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
  invalidateGetCache(['/connectors', '/documents', '/jobs', '/intelligence']);
  return connector;
}

export async function deleteConnector(connectorId: string): Promise<void> {
  await request<void>(`/connectors/${connectorId}`, {
    method: 'DELETE',
  });
  invalidateGetCache(['/connectors', '/documents', '/jobs', '/intelligence']);
}

export async function testConnector(connectorId: string): Promise<{ ok: boolean; message: string }> {
  return request<{ ok: boolean; message: string }>(`/connectors/${connectorId}/test`, { method: 'POST' });
}

export async function syncConnector(connectorId: string, fullReindex = false): Promise<SyncJob> {
  const job = await request<SyncJob>(`/connectors/${connectorId}/sync`, {
    method: 'POST',
    body: JSON.stringify({ full_reindex: fullReindex }),
  });
  invalidateGetCache(['/jobs', '/documents', '/intelligence']);
  return job;
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
  if (filters.document_type) params.set('document_type', filters.document_type);
  if (filters.business_domain) params.set('business_domain', filters.business_domain);
  if (filters.parse_status) params.set('parse_status', filters.parse_status);
  if (filters.source_type) params.set('source_type', filters.source_type);
  if (filters.needs_review) params.set('needs_review', 'true');
  if (filters.low_confidence) params.set('low_confidence', 'true');
  params.set('page', String(filters.page ?? 1));
  params.set('page_size', String(filters.page_size ?? 200));
  const suffix = params.toString();
  const path = `/documents${suffix ? `?${suffix}` : ''}`;
  const cacheKey = `/documents:${suffix}`;
  const response = await cachedGet<DocumentListResponse>(cacheKey, 5_000, () =>
    request<DocumentListResponse>(path),
  );
  return response.items;
}

export async function getDocument(documentId: string): Promise<DocumentDetail> {
  return request<DocumentDetail>(`/documents/${documentId}`);
}

export async function getIntelligenceOverview(params?: {
  task_search?: string;
  blocked_by_task_id?: string;
}): Promise<IntelligenceOverview> {
  const query = new URLSearchParams();
  if (params?.task_search) {
    query.set('task_search', params.task_search);
  }
  if (params?.blocked_by_task_id) {
    query.set('blocked_by_task_id', params.blocked_by_task_id);
  }
  const suffix = query.toString();
  const path = `/intelligence/overview${suffix ? `?${suffix}` : ''}`;
  const cacheKey = `/intelligence/overview:${suffix}`;
  return cachedGet<IntelligenceOverview>(cacheKey, 5_000, () =>
    request<IntelligenceOverview>(path),
  );
}

export function getDocumentOriginalUrl(documentId: string): string {
  return `${API_BASE}/documents/${documentId}/original`;
}

export async function reindexDocument(documentId: string): Promise<{ status: string; task_id: string; document_id: string }> {
  const result = await request<{ status: string; task_id: string; document_id: string }>(`/documents/${documentId}/reindex`, {
    method: 'POST',
  });
  invalidateGetCache(['/documents', '/jobs', '/intelligence']);
  return result;
}

export async function updateDocumentClassification(
  documentId: string,
  payload: { document_type: string; business_domain: string; document_type_reason?: string; business_domain_reason?: string },
): Promise<DocumentDetail> {
  const detail = await request<DocumentDetail>(`/documents/${documentId}/classification`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
  invalidateGetCache(['/documents', '/intelligence']);
  return detail;
}

export async function listJobs(): Promise<SyncJob[]> {
  const response = await cachedGet<SyncJobListResponse>('/jobs', 3_000, () =>
    request<SyncJobListResponse>('/jobs?page=1&page_size=200'),
  );
  return response.items;
}

export async function retryJob(jobId: string): Promise<SyncJob> {
  const job = await request<SyncJob>(`/jobs/${jobId}/retry`, {
    method: 'POST',
  });
  invalidateGetCache(['/jobs']);
  return job;
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

export async function deleteUser(userId: string): Promise<void> {
  return request<void>(`/users/${userId}`, {
    method: 'DELETE',
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
