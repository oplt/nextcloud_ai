import type {
  AuthSession,
  ChatAskResponse,
  ChatSessionDetail,
  ChatSessionSummary,
  Connector,
  ConnectorPayload,
  DocumentDetail,
  DocumentSummary,
  SyncJob,
  User,
} from '../types/api';

const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api/v1').replace(/\/$/, '');
const TOKEN_KEY = 'nc_ai_access_token';

export function getStoredToken(): string | null {
  return window.localStorage.getItem(TOKEN_KEY);
}

export function storeToken(token: string | null): void {
  if (token) {
    window.localStorage.setItem(TOKEN_KEY, token);
    return;
  }
  window.localStorage.removeItem(TOKEN_KEY);
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers ?? {});
  const token = getStoredToken();
  const hasFormData = options.body instanceof FormData;

  if (!hasFormData && !headers.has('Content-Type') && options.method && options.method !== 'GET') {
    headers.set('Content-Type', 'application/json');
  }
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
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
    // For auth/me endpoint with 401, return a special error
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
  const session = await request<AuthSession>('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  });
  storeToken(session.access_token);
  return session;
}

export async function logout(): Promise<void> {
  await request<void>('/auth/logout', { method: 'POST' });
  storeToken(null);
}

export async function getCurrentUser(): Promise<User> {
  return request<User>('/auth/me');
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

export async function listDocuments(query?: string): Promise<DocumentSummary[]> {
  const params = new URLSearchParams();
  if (query) {
    params.set('query', query);
  }
  const suffix = params.toString();
  return request<DocumentSummary[]>(`/documents${suffix ? `?${suffix}` : ''}`);
}

export async function getDocument(documentId: string): Promise<DocumentDetail> {
  return request<DocumentDetail>(`/documents/${documentId}`);
}

export async function reindexDocument(documentId: string): Promise<{ status: string; task_id: string; document_id: string }> {
  return request<{ status: string; task_id: string; document_id: string }>(`/documents/${documentId}/reindex`, {
    method: 'POST',
  });
}

export async function listJobs(): Promise<SyncJob[]> {
  return request<SyncJob[]>('/jobs');
}

export async function listChatSessions(): Promise<ChatSessionSummary[]> {
  return request<ChatSessionSummary[]>('/chat/sessions');
}

export async function getChatSession(sessionId: string): Promise<ChatSessionDetail> {
  return request<ChatSessionDetail>(`/chat/sessions/${sessionId}`);
}

export async function askChat(question: string, sessionId?: string | null): Promise<ChatAskResponse> {
  return request<ChatAskResponse>('/chat/ask', {
    method: 'POST',
    body: JSON.stringify({ question, session_id: sessionId ?? null, top_k: 6 }),
  });
}
