import type { ReactNode } from 'react';

type EmptyStateProps = {
  title: string;
  description?: string;
  icon?: ReactNode;
  action?: ReactNode;
  className?: string;
};

export function EmptyState({ title, description, icon, action, className = '' }: EmptyStateProps) {
  return (
    <div className={`empty-state empty-state--ui ${className}`.trim()}>
      {icon ? <div className="empty-state__icon">{icon}</div> : null}
      <strong>{title}</strong>
      {description ? <span>{description}</span> : null}
      {action ? <div className="empty-state__action">{action}</div> : null}
    </div>
  );
}
