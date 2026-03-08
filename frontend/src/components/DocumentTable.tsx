import type { DocumentSummary } from '../types/api';
import { formatDateTime, getDocumentTypeLabel } from '../utils/documentDisplay';

export type DocumentSortColumn = 'name' | 'type' | 'status' | 'updated';
export type SortDirection = 'asc' | 'desc';

type DocumentTableProps = {
  documents: DocumentSummary[];
  totalDocuments: number;
  selectedDocumentId: string | null;
  sortColumn: DocumentSortColumn;
  sortDirection: SortDirection;
  currentPage: number;
  totalPages: number;
  rowsPerPage: number;
  onPageChange: (page: number) => void;
  onSort: (column: DocumentSortColumn) => void;
  onSelect: (document: DocumentSummary) => void;
};

const columns: Array<{ key: DocumentSortColumn; label: string }> = [
  { key: 'name', label: 'Name' },
  { key: 'type', label: 'Type' },
  { key: 'status', label: 'Status' },
  { key: 'updated', label: 'Updated' },
];

export function DocumentTable({
  documents,
  totalDocuments,
  selectedDocumentId,
  sortColumn,
  sortDirection,
  currentPage,
  totalPages,
  rowsPerPage,
  onPageChange,
  onSort,
  onSelect,
}: DocumentTableProps) {
  const getSortLabel = (column: DocumentSortColumn) => {
    if (sortColumn !== column) {
      return 'Sort';
    }

    return sortDirection === 'asc' ? 'Sorted ascending' : 'Sorted descending';
  };

  const firstRow = totalDocuments === 0 ? 0 : (currentPage - 1) * rowsPerPage + 1;
  const lastRow = totalDocuments === 0 ? 0 : firstRow + documents.length - 1;

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
              {columns.map((column) => (
                <th
                  key={column.key}
                  aria-sort={
                    sortColumn === column.key
                      ? sortDirection === 'asc'
                        ? 'ascending'
                        : 'descending'
                      : 'none'
                  }
                >
                  <button
                    type="button"
                    className={sortColumn === column.key ? 'sort-button sort-button--active' : 'sort-button'}
                    onClick={() => onSort(column.key)}
                    aria-label={`${column.label}. ${getSortLabel(column.key)}`}
                  >
                    <span>{column.label}</span>
                    <span className="sort-button__icon" aria-hidden="true">
                      {sortColumn === column.key ? (sortDirection === 'asc' ? '↑' : '↓') : '↕'}
                    </span>
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {documents.map((document) => (
              <tr
                key={document.id}
                className={selectedDocumentId === document.id ? 'is-selected' : ''}
                onClick={() => onSelect(document)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    onSelect(document);
                  }
                }}
                tabIndex={0}
                role="button"
              >
                <td>
                  <strong>{document.file_name}</strong>
                  <small>{document.file_path}</small>
                </td>
                <td>
                  <strong>{getDocumentTypeLabel(document)}</strong>
                  <small>{document.mime_type ?? 'No mime type'}</small>
                </td>
                <td>
                  <span className={`pill pill--${document.parse_status}`}>{document.parse_status}</span>
                </td>
                <td>{formatDateTime(document.modified_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <footer className="document-table__footer">
        <p>
          Showing {firstRow}-{lastRow} of {totalDocuments}
        </p>
        <div className="pagination-controls">
          <button type="button" onClick={() => onPageChange(currentPage - 1)} disabled={currentPage <= 1}>
            Previous
          </button>
          <span>
            Page {currentPage} / {totalPages}
          </span>
          <button type="button" onClick={() => onPageChange(currentPage + 1)} disabled={currentPage >= totalPages}>
            Next
          </button>
        </div>
      </footer>
    </div>
  );
}
