import type {
  ChatActiveContextDocument,
  ChatMessage,
  ChatSource,
} from '../../types/api';

export type SourcesByMessageId = Record<string, ChatSource[]>;

export function parseCitations(
  citations: Array<Record<string, unknown>> | null | undefined,
): ChatSource[] {
  if (!Array.isArray(citations) || citations.length === 0) {
    return [];
  }

  return citations.filter(
    (citation): citation is ChatSource =>
      typeof citation === 'object' &&
      citation !== null &&
      typeof citation.chunk_id === 'string' &&
      typeof citation.document_id === 'string' &&
      typeof citation.file_name === 'string' &&
      typeof citation.file_path === 'string' &&
      typeof citation.snippet === 'string' &&
      typeof citation.score === 'number',
  );
}

export function buildSourcesByMessageId(messages: ChatMessage[]): SourcesByMessageId {
  const sourcesByMessageId: SourcesByMessageId = {};

  for (const message of messages) {
    if (message.role !== 'assistant') {
      continue;
    }

    const sources = parseCitations(message.citations_json);
    if (sources.length > 0) {
      sourcesByMessageId[message.id] = sources;
    }
  }

  return sourcesByMessageId;
}

export function getLastAssistantMessageId(messages: ChatMessage[]): string | null {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    if (messages[index]?.role === 'assistant') {
      return messages[index].id;
    }
  }

  return null;
}

export function getPanelSources(
  sourcesByMessageId: SourcesByMessageId,
  activeMessageId: string | null,
): ChatSource[] {
  if (!activeMessageId) {
    return [];
  }

  return sourcesByMessageId[activeMessageId] ?? [];
}

export function mergeActiveContextDocuments(
  sources: ChatSource[],
  explicitContextDocuments: ChatActiveContextDocument[] = [],
): ChatActiveContextDocument[] {
  const byDocumentId = new Map<string, ChatActiveContextDocument>();

  for (const document of explicitContextDocuments) {
    byDocumentId.set(document.document_id, document);
  }

  for (const source of sources) {
    if (!byDocumentId.has(source.document_id)) {
      byDocumentId.set(source.document_id, {
        document_id: source.document_id,
        file_name: source.file_name,
        file_path: source.file_path,
      });
    }
  }

  return [...byDocumentId.values()];
}

export function isAssistantMessage(message: ChatMessage): boolean {
  return message.role === 'assistant';
}
