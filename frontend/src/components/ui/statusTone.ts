export type StatusTone = 'neutral' | 'success' | 'warning' | 'danger' | 'info';

export function statusToneFromValue(value: string): StatusTone {
  const normalized = value.toLowerCase();
  if (['succeeded', 'completed', 'done', 'indexed', 'healthy', 'approved'].includes(normalized)) {
    return 'success';
  }
  if (['failed', 'error', 'dead_lettered', 'dismissed'].includes(normalized)) {
    return 'danger';
  }
  if (['warning', 'needs_review', 'retrying'].includes(normalized)) {
    return 'warning';
  }
  if (['queued', 'pending', 'in_progress', 'running', 'processing', 'blocked'].includes(normalized)) {
    return 'info';
  }
  return 'neutral';
}
