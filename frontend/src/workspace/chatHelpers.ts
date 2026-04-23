import type { ChatMessage, RetrievalFilterFormState } from '../types/api';

export const EMPTY_CHAT_FILTERS: RetrievalFilterFormState = {
  connector_id: '',
  mime_type: '',
  path_prefix: '',
  modified_after: '',
  modified_before: '',
};

export function createLocalChatMessage(
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

export function getLastAssistantMessageId(messages: ChatMessage[]): string | null {
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    if (messages[i].role === 'assistant') {
      return messages[i].id;
    }
  }
  return null;
}

export function extractActiveContextDocumentIds(messages: ChatMessage[]): string[] {
  const last = [...messages].reverse().find((message) => message.role === 'assistant');
  const citations = Array.isArray(last?.citations_json) ? last.citations_json : [];
  const ids: string[] = [];
  for (const citation of citations) {
    const id = typeof citation.document_id === 'string' ? citation.document_id : null;
    if (id && !ids.includes(id)) {
      ids.push(id);
    }
  }
  return ids;
}

export function getUserInitials(name: string | null | undefined): string {
  const parts = name?.trim().split(/\s+/).filter(Boolean) ?? [];
  if (!parts.length) return 'NC';
  return parts
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? '')
    .join('');
}

export function toIsoDayBoundary(dateValue: string, kind: 'start' | 'end'): string | null {
  if (!dateValue) {
    return null;
  }
  const suffix = kind === 'start' ? 'T00:00:00.000Z' : 'T23:59:59.999Z';
  return new Date(`${dateValue}${suffix}`).toISOString();
}

export function buildRetrievalFilters(filters: RetrievalFilterFormState) {
  const payload = {
    connector_ids: filters.connector_id ? [filters.connector_id] : [],
    mime_types: filters.mime_type ? [filters.mime_type] : [],
    path_prefixes: filters.path_prefix ? [filters.path_prefix] : [],
    modified_after: toIsoDayBoundary(filters.modified_after, 'start'),
    modified_before: toIsoDayBoundary(filters.modified_before, 'end'),
  };

  const hasFilters =
    payload.connector_ids.length > 0 ||
    payload.mime_types.length > 0 ||
    payload.path_prefixes.length > 0 ||
    Boolean(payload.modified_after) ||
    Boolean(payload.modified_before);

  return hasFilters ? payload : undefined;
}
