import type { DocumentSummary } from '../types/api';
import { formatDateTime, getDocumentTypeLabel } from '../utils/documentDisplay';

export type DocumentSortColumn = 'name' | 'type' | 'status' | 'updated';
export type SortDirection       = 'asc' | 'desc';

type DocumentTableProps = {
  documents: DocumentSummary[];
  totalDocuments: number;
  selectedDocumentId: string | null;
  sortColumn: DocumentSortColumn;
  sortDirection: SortDirection;
  currentPage: number;
  totalPages: number;
  rowsPerPage: number;
  loading?: boolean;
  onPageChange: (page: number) => void;
  onSort: (column: DocumentSortColumn) => void;
  onSelect: (document: DocumentSummary) => void;
};

const columns: Array<{ key: DocumentSortColumn; label: string }> = [
  { key: 'name',    label: 'Name'    },
  { key: 'type',    label: 'Type'    },
  { key: 'status',  label: 'Status'  },
  { key: 'updated', label: 'Updated' },
];

function SkeletonRows() {
  return (
    <>
      {Array.from({ length: 6 }, (_, i) => (
        <tr key={i} aria-hidden="true">
          <td>
            <div className="skeleton skeleton-text" style={{ width: '62%' }} />
            <div className="skeleton skeleton-text" style={{ width: '40%', marginTop: 6 }} />
          </td>
          <td><div className="skeleton skeleton-text" style={{ width: '44%' }} /></td>
          <td><div className="skeleton skeleton-pill" /></td>
          <td><div className="skeleton skeleton-text" style={{ width: '70%' }} /></td>
        </tr>
      ))}
    </>
  );
}

export function DocumentTable({
  documents,
  totalDocuments,
  selectedDocumentId,
  sortColumn,
  sortDirection,
  currentPage,
  totalPages,
  rowsPerPage,
  loading = false,
  onPageChange,
  onSort,
  onSelect,
}: DocumentTableProps) {
  const ariaSort = (col: DocumentSortColumn) => {
    if (sortColumn !== col) return 'none' as const;
    return sortDirection === 'asc' ? ('ascending' as const) : ('descending' as const);
  };

  const firstRow = totalDocuments === 0 ? 0 : (currentPage - 1) * rowsPerPage + 1;
  const lastRow  = totalDocuments === 0 ? 0 : firstRow + documents.length - 1;

  return (
    <div className="card table-card document-table-card">
      <header className="panel-header">
        <h3>Documents</h3>
        <span>{totalDocuments}</span>
      </header>

      <div className="table-wrap">
        <table className="document-table">
          <thead>
            <tr>
              {columns.map((col) => (
                <th key={col.key} aria-sort={ariaSort(col.key)}>
                  <button
                    type="button"
                    className={`sort-button${sortColumn === col.key ? ' sort-button--active' : ''}`}
                    onClick={() => onSort(col.key)}
                    aria-label={`Sort by ${col.label}${sortColumn === col.key ? `, currently ${sortDirection}ending` : ''}`}
                  >
                    <span>{col.label}</span>
                    <span className="sort-button__icon" aria-hidden="true">
                      {sortColumn === col.key ? (sortDirection === 'asc' ? '↑' : '↓') : '↕'}
                    </span>
                  </button>
                </th>
              ))}
            </tr>
          </thead>

          <tbody>
            {loading ? (
              <SkeletonRows />
            ) : (
              documents.map((doc) => (
                <tr
                  key={doc.id}
                  className={selectedDocumentId === doc.id ? 'is-selected' : ''}
                  onClick={() => onSelect(doc)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      onSelect(doc);
                    }
                  }}
                  tabIndex={0}
                  role="button"
                  aria-selected={selectedDocumentId === doc.id}
                >
                  <td>
                    <strong>{doc.file_name}</strong>
                    <small title={doc.file_path}>{doc.file_path}</small>
                  </td>
                  <td>
                    <strong>{getDocumentTypeLabel(doc)}</strong>
                    <small>{doc.mime_type ?? '—'}</small>
                  </td>
                  <td>
                    <span className={`pill pill--${doc.parse_status}`}>{doc.parse_status}</span>
                  </td>
                  <td>{formatDateTime(doc.modified_at)}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <footer className="document-table__footer">
        <p>
          {totalDocuments === 0
            ? 'No documents'
            : `Showing ${firstRow}–${lastRow} of ${totalDocuments}`}
        </p>
        <div className="pagination-controls">
          <button
            type="button"
            onClick={() => onPageChange(currentPage - 1)}
            disabled={currentPage <= 1}
            aria-label="Previous page"
          >
            ← Prev
          </button>
          <span aria-live="polite">{currentPage} / {totalPages}</span>
          <button
            type="button"
            onClick={() => onPageChange(currentPage + 1)}
            disabled={currentPage >= totalPages}
            aria-label="Next page"
          >
            Next →
          </button>
        </div>
      </footer>
    </div>
  );
}
