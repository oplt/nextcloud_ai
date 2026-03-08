import type { DocumentSummary } from '../types/api';

type DocumentDisplayShape = Pick<DocumentSummary, 'file_name' | 'mime_type'>;

const MIME_TYPE_LABELS: Record<string, string> = {
  'application/pdf': 'PDF',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'DOCX',
  'application/vnd.oasis.opendocument.text': 'ODT',
  'text/plain': 'TXT',
  'text/markdown': 'MD',
  'text/x-markdown': 'MD',
};

export function getDocumentTypeLabel(document: DocumentDisplayShape): string {
  const suffix = document.file_name.split('.').pop()?.trim().toUpperCase();

  if (suffix && suffix !== document.file_name.trim().toUpperCase()) {
    return suffix;
  }

  if (document.mime_type) {
    return MIME_TYPE_LABELS[document.mime_type] ?? document.mime_type.split('/').pop()?.toUpperCase() ?? 'Unknown';
  }

  return 'Unknown';
}

export function formatDateTime(value: string | null): string {
  return value ? new Date(value).toLocaleString() : 'Unknown';
}

export function formatFileSize(value: number | null): string {
  if (value === null || Number.isNaN(value)) {
    return 'Unknown';
  }

  if (value < 1024) {
    return `${value} B`;
  }

  const units = ['KB', 'MB', 'GB', 'TB'];
  let size = value / 1024;
  let unitIndex = 0;

  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }

  const fractionDigits = size >= 100 ? 0 : 1;
  return `${size.toFixed(fractionDigits)} ${units[unitIndex]}`;
}
