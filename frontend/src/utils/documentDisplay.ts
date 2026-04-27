import type { DocumentSummary } from '../types/api';

type DocumentDisplayShape = Pick<DocumentSummary, 'file_name' | 'mime_type' | 'document_type' | 'document_type_confidence' | 'business_domain'>;

const MIME_TYPE_LABELS: Record<string, string> = {
  'application/pdf': 'PDF',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'DOCX',
  'application/vnd.oasis.opendocument.text': 'ODT',
  'text/plain': 'TXT',
  'text/markdown': 'MD',
  'text/x-markdown': 'MD',
};

const DOCUMENT_TYPE_ALIASES: Record<string, string> = {
  email: 'email_correspondence',
  meeting: 'meeting_notes',
  policy: 'policy_document',
  general: 'general_knowledge',
};

export function getDocumentTypeLabel(document: DocumentDisplayShape): string {
  const documentType = DOCUMENT_TYPE_ALIASES[document.document_type] ?? document.document_type;
  if (documentType && documentType !== 'general_knowledge') {
    if (documentType === 'unclassified' || document.document_type_confidence < 0.6) {
      return 'Unclassified';
    }
    return formatTaxonomyLabel(documentType);
  }
  const suffix = document.file_name.split('.').pop()?.trim().toUpperCase();

  if (suffix && suffix !== document.file_name.trim().toUpperCase()) {
    return suffix;
  }

  if (document.mime_type) {
    return MIME_TYPE_LABELS[document.mime_type] ?? document.mime_type.split('/').pop()?.toUpperCase() ?? 'Unknown';
  }

  return 'Unknown';
}

export function getBusinessDomainLabel(document: Pick<DocumentSummary, 'business_domain'>): string {
  return document.business_domain === 'unknown' ? 'Unknown' : formatTaxonomyLabel(document.business_domain);
}

export function formatTaxonomyLabel(value: string): string {
  return value
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

export function formatConfidence(value: number | null | undefined): string {
  if (typeof value !== 'number' || Number.isNaN(value)) return '0%';
  return `${Math.round(value * 100)}%`;
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
