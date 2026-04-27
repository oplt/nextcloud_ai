import type { ReactNode } from 'react';

import { AppCard } from './AppCard';

type DataTableProps = {
  title: string;
  count?: number;
  className?: string;
  headerActions?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  collapsed?: boolean;
  tableId?: string;
};

export function DataTable({
  title,
  count,
  className = '',
  headerActions,
  children,
  footer,
  collapsed = false,
  tableId,
}: DataTableProps) {
  return (
    <AppCard className={`card table-card ${className}`.trim()}>
      <header className="panel-header">
        <h3>{title}</h3>
        <div className="data-table__header-actions">
          {headerActions}
          {typeof count === 'number' ? <span>{count}</span> : null}
        </div>
      </header>
      <div id={tableId} className="table-wrap" hidden={collapsed}>
        {children}
      </div>
      {footer && !collapsed ? <footer className="document-table__footer">{footer}</footer> : null}
    </AppCard>
  );
}
