import type { ReactNode } from 'react';
import type { StatusTone } from './statusTone';

type StatusBadgeProps = {
  label: string;
  tone?: StatusTone;
  className?: string;
  children?: ReactNode;
};

export function StatusBadge({ label, tone = 'neutral', className = '', children }: StatusBadgeProps) {
  return (
    <span className={`status-badge status-badge--${tone} ${className}`.trim()}>
      {children ?? label}
    </span>
  );
}
