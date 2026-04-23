import { useCallback, useMemo, useState } from 'react';

import { AppButton } from '../components/ui/AppButton';
import { AppCard } from '../components/ui/AppCard';
import { AppSelectField } from '../components/ui/AppSelectField';
import { AppTextField } from '../components/ui/AppTextField';
import type { Connector, DocumentDetail, DocumentFilterFormState, DocumentSummary } from '../types/api';
import {
  DocumentTable,
  type DocumentSortColumn,
  type SortDirection,
} from '../components/DocumentTable';
import { DocumentViewer } from '../components/DocumentViewer';
import { getDocumentTypeLabel } from '../utils/documentDisplay';

const ROWS_PER_PAGE = 20;
const INITIAL_FILTERS: DocumentFilterFormState = {
  query: '',
  connector_id: '',
  mime_type: '',
  path_prefix: '',
  modified_after: '',
  modified_before: '',
};

type DocumentsPageProps = {
  documents: DocumentSummary[];
  connectors: Connector[];
  selectedDocumentId: string | null;
  selectedDocument: DocumentDetail | null;
  viewLoading?: boolean;
  viewError?: string | null;
  onSelect: (document: DocumentSummary) => Promise<void>;
  onReindex: (documentId: string) => Promise<void>;
};

export function DocumentsPage({
  documents,
  connectors,
  selectedDocumentId,
  selectedDocument,
  viewLoading = false,
  viewError = null,
  onSelect,
  onReindex,
}: DocumentsPageProps) {
  const [filters, setFilters] = useState<DocumentFilterFormState>(INITIAL_FILTERS);
  const [sortColumn, setSortColumn] = useState<DocumentSortColumn>('updated');
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc');
  const [currentPage, setCurrentPage] = useState(1);

  const availableMimeTypes = useMemo(
    () =>
      Array.from(new Set(documents.map((document) => document.mime_type).filter(Boolean) as string[])).sort(),
    [documents],
  );

  const filteredDocuments = useMemo(() => {
    return documents.filter((document) => {
      const query = filters.query.trim().toLowerCase();
      if (query) {
        const haystack = `${document.file_name} ${document.file_path}`.toLowerCase();
        if (!haystack.includes(query)) {
          return false;
        }
      }
      if (filters.connector_id && document.connector_id !== filters.connector_id) {
        return false;
      }
      if (filters.mime_type && document.mime_type !== filters.mime_type) {
        return false;
      }
      if (filters.path_prefix && !document.file_path.startsWith(filters.path_prefix)) {
        return false;
      }
      if (filters.modified_after && (!document.modified_at || document.modified_at < filters.modified_after)) {
        return false;
      }
      if (filters.modified_before && (!document.modified_at || document.modified_at > filters.modified_before)) {
        return false;
      }
      return true;
    });
  }, [documents, filters]);

  const sortedDocuments = useMemo(() => {
    return [...filteredDocuments].sort((a, b) => {
      const dir = sortDirection === 'asc' ? 1 : -1;

      if (sortColumn === 'updated') {
        const at = a.modified_at ? new Date(a.modified_at).getTime() : Number.NEGATIVE_INFINITY;
        const bt = b.modified_at ? new Date(b.modified_at).getTime() : Number.NEGATIVE_INFINITY;
        if (at !== bt) return (at - bt) * dir;
        return a.file_name.localeCompare(b.file_name) * dir;
      }

      if (sortColumn === 'type') {
        const comparison = getDocumentTypeLabel(a).localeCompare(getDocumentTypeLabel(b));
        if (comparison !== 0) return comparison * dir;
        return a.file_name.localeCompare(b.file_name) * dir;
      }

      if (sortColumn === 'status') {
        const comparison = a.parse_status.localeCompare(b.parse_status);
        if (comparison !== 0) return comparison * dir;
        return a.file_name.localeCompare(b.file_name) * dir;
      }

      return a.file_name.localeCompare(b.file_name) * dir;
    });
  }, [filteredDocuments, sortColumn, sortDirection]);

  const totalPages = Math.max(1, Math.ceil(sortedDocuments.length / ROWS_PER_PAGE));
  const effectiveCurrentPage = Math.min(currentPage, totalPages);

  const paginatedDocuments = useMemo(() => {
    const start = (effectiveCurrentPage - 1) * ROWS_PER_PAGE;
    return sortedDocuments.slice(start, start + ROWS_PER_PAGE);
  }, [effectiveCurrentPage, sortedDocuments]);

  const handleSort = useCallback(
    (column: DocumentSortColumn) => {
      setCurrentPage(1);
      if (column === sortColumn) {
        setSortDirection((direction) => (direction === 'asc' ? 'desc' : 'asc'));
      } else {
        setSortColumn(column);
        setSortDirection(column === 'updated' ? 'desc' : 'asc');
      }
    },
    [sortColumn],
  );

  const updateFilters = useCallback((patch: Partial<DocumentFilterFormState>) => {
    setCurrentPage(1);
    setFilters((current) => ({ ...current, ...patch }));
  }, []);

  return (
    <section className="split-layout split-layout--wide">
      <div className="documents-panel">
        {viewError ? (
          <div className="page-alert page-alert--error" role="alert">
            {viewError}
          </div>
        ) : null}
        {viewLoading ? (
          <div className="page-alert page-alert--info" role="status">
            Refreshing document catalog…
          </div>
        ) : null}
        <AppCard component="section" className="card filter-card">
          <header className="panel-header">
            <div>
              <h3>Document filters</h3>
              <p className="filter-card__meta">Slice the catalog by connector, file type, path, and modified date.</p>
            </div>
            <AppButton type="button" variant="outlined" onClick={() => updateFilters(INITIAL_FILTERS)}>
              Reset
            </AppButton>
          </header>

          <div className="filter-grid">
            <AppTextField
              label="Search"
              value={filters.query}
              onChange={(event) => updateFilters({ query: event.target.value })}
              placeholder="policy, handbook, invoice"
            />

            <AppSelectField
              label="Connector"
              value={filters.connector_id}
              onChange={(event) => updateFilters({ connector_id: event.target.value })}
              options={[
                { label: 'All connectors', value: '' },
                ...connectors.map((connector) => ({ label: connector.display_name, value: connector.id })),
              ]}
            />

            <AppSelectField
              label="File type"
              value={filters.mime_type}
              onChange={(event) => updateFilters({ mime_type: event.target.value })}
              options={[
                { label: 'All types', value: '' },
                ...availableMimeTypes.map((mimeType) => ({ label: mimeType, value: mimeType })),
              ]}
            />

            <AppTextField
              label="Path prefix"
              value={filters.path_prefix}
              onChange={(event) => updateFilters({ path_prefix: event.target.value })}
              placeholder="/departments/hr"
            />

            <AppTextField
              label="Modified after"
              type="date"
              value={filters.modified_after}
              onChange={(event) => updateFilters({ modified_after: event.target.value })}
              InputLabelProps={{ shrink: true }}
            />

            <AppTextField
              label="Modified before"
              type="date"
              value={filters.modified_before}
              onChange={(event) => updateFilters({ modified_before: event.target.value })}
              InputLabelProps={{ shrink: true }}
            />
          </div>
        </AppCard>

        <DocumentTable
          documents={paginatedDocuments}
          totalDocuments={sortedDocuments.length}
          selectedDocumentId={selectedDocumentId}
          sortColumn={sortColumn}
          sortDirection={sortDirection}
          currentPage={effectiveCurrentPage}
          totalPages={totalPages}
          rowsPerPage={ROWS_PER_PAGE}
          sectionCollapsible
          onPageChange={setCurrentPage}
          onSort={handleSort}
          onSelect={(document) => void onSelect(document)}
        />
      </div>

      <DocumentViewer document={selectedDocument} onReindex={onReindex} />
    </section>
  );
}
