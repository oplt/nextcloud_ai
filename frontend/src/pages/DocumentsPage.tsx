import { useCallback, useMemo, useState } from 'react';
import Alert from '@mui/material/Alert';
import Drawer from '@mui/material/Drawer';

import { AppButton } from '../components/ui/AppButton';
import { AppCard } from '../components/ui/AppCard';
import { DrawerForm } from '../components/ui/DrawerForm';
import { EmptyState } from '../components/ui/EmptyState';
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
  document_type: '',
  business_domain: '',
  parse_status: '',
  needs_review: false,
};

const DOCUMENT_FILTERS = [
  { label: 'All', value: '' },
  { label: 'Contracts', value: 'contract' },
  { label: 'Finance', value: 'invoice_finance' },
  { label: 'Legal', value: 'legal' },
  { label: 'Compliance', value: 'compliance' },
  { label: 'Meeting Notes', value: 'meeting_notes' },
  { label: 'Technical Docs', value: 'technical_documentation' },
  { label: 'HR', value: 'hr' },
  { label: 'Sales/Proposals', value: 'sales_proposal' },
  { label: 'Project Docs', value: 'project_document' },
  { label: 'Unclassified', value: 'unclassified' },
];

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
  const [viewerOpen, setViewerOpen] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(false);

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
      if (filters.document_type && document.document_type !== filters.document_type) {
        return false;
      }
      if (filters.business_domain && document.business_domain !== filters.business_domain) {
        return false;
      }
      if (filters.parse_status && document.parse_status !== filters.parse_status) {
        return false;
      }
      if (filters.needs_review && !document.needs_review) {
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
      if (sortColumn === 'domain') {
        const comparison = a.business_domain.localeCompare(b.business_domain);
        if (comparison !== 0) return comparison * dir;
        return a.file_name.localeCompare(b.file_name) * dir;
      }
      if (sortColumn === 'confidence') {
        const ac = Math.min(a.document_type_confidence, a.business_domain_confidence);
        const bc = Math.min(b.document_type_confidence, b.business_domain_confidence);
        if (ac !== bc) return (ac - bc) * dir;
        return a.file_name.localeCompare(b.file_name) * dir;
      }

      return a.file_name.localeCompare(b.file_name) * dir;
    });
  }, [filteredDocuments, sortColumn, sortDirection]);

  const totalPages = Math.max(1, Math.ceil(sortedDocuments.length / ROWS_PER_PAGE));
  const effectiveCurrentPage = Math.min(currentPage, totalPages);
  const activeFilterCount = useMemo(
    () =>
      [
        filters.query,
        filters.connector_id,
        filters.mime_type,
        filters.path_prefix,
        filters.modified_after,
        filters.modified_before,
        filters.document_type,
        filters.business_domain,
        filters.parse_status,
        filters.needs_review ? 'needs_review' : '',
      ].filter(Boolean).length,
    [filters],
  );

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

  const handleSelectDocument = useCallback(
    async (document: DocumentSummary) => {
      await onSelect(document);
      setViewerOpen(true);
    },
    [onSelect],
  );

  const handleCloseViewer = useCallback(() => {
    setViewerOpen(false);
  }, []);

  return (
    <section className="documents-page">
      <div className="documents-panel">
        {viewError ? (
          <Alert severity="error" className="page-alert">
            {viewError}
          </Alert>
        ) : null}
        {viewLoading ? (
          <Alert severity="info" className="page-alert" role="status">
            Refreshing document catalog…
          </Alert>
        ) : null}
        <AppCard component="section" className="card filter-card filter-card--compact">
          <header className="panel-header">
            <div>
              <h3>Catalog controls</h3>
              <p className="filter-card__meta">
                {activeFilterCount > 0
                  ? `${activeFilterCount} filters active`
                  : 'No active filters'}
              </p>
            </div>
            <div className="documents-controls">
              <AppButton type="button" variant="outlined" onClick={() => setFiltersOpen(true)}>
                Filters
              </AppButton>
              <AppButton type="button" variant="text" onClick={() => updateFilters(INITIAL_FILTERS)}>
                Reset
              </AppButton>
            </div>
          </header>
        </AppCard>

        <DrawerForm
          open={filtersOpen}
          onClose={() => setFiltersOpen(false)}
          title="Document filters"
          description="Slice the catalog by connector, type, path, and review signals."
          actions={
            <>
              <AppButton type="button" variant="text" onClick={() => updateFilters(INITIAL_FILTERS)}>
                Reset
              </AppButton>
              <AppButton type="button" onClick={() => setFiltersOpen(false)}>
                Apply
              </AppButton>
            </>
          }
        >
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
              label="Document type"
              value={filters.document_type}
              onChange={(event) => updateFilters({ document_type: event.target.value })}
              options={DOCUMENT_FILTERS}
            />

            <AppSelectField
              label="Business domain"
              value={filters.business_domain}
              onChange={(event) => updateFilters({ business_domain: event.target.value })}
              options={[
                { label: 'All domains', value: '' },
                { label: 'Finance', value: 'finance' },
                { label: 'Legal', value: 'legal' },
                { label: 'Compliance', value: 'compliance' },
                { label: 'Engineering', value: 'engineering' },
                { label: 'HR', value: 'hr' },
                { label: 'Operations', value: 'operations' },
                { label: 'Sales', value: 'sales' },
                { label: 'Unknown', value: 'unknown' },
              ]}
            />

            <AppSelectField
              label="Parse status"
              value={filters.parse_status}
              onChange={(event) => updateFilters({ parse_status: event.target.value })}
              options={[
                { label: 'All statuses', value: '' },
                { label: 'Indexed', value: 'indexed' },
                { label: 'Failed Parsing', value: 'failed' },
                { label: 'Needs OCR', value: 'needs_ocr' },
                { label: 'Unsupported', value: 'unsupported_type' },
                { label: 'Pending', value: 'pending' },
              ]}
            />

            <AppSelectField
              label="File type"
              value={filters.mime_type}
              onChange={(event) => updateFilters({ mime_type: event.target.value })}
              options={[
                { label: 'All MIME types', value: '' },
                ...availableMimeTypes.map((mimeType) => ({ label: mimeType, value: mimeType })),
              ]}
            />

            <AppTextField
              label="Path prefix"
              value={filters.path_prefix}
              onChange={(event) => updateFilters({ path_prefix: event.target.value })}
              placeholder="/departments/hr"
            />

            <AppSelectField
              label="Review"
              value={filters.needs_review ? 'needs_review' : ''}
              onChange={(event) => updateFilters({ needs_review: event.target.value === 'needs_review' })}
              options={[
                { label: 'All review states', value: '' },
                { label: 'Needs Review', value: 'needs_review' },
              ]}
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
        </DrawerForm>

        {sortedDocuments.length === 0 ? (
          <EmptyState
            title="No matching documents"
            description="Adjust filters or run a new connector sync."
          />
        ) : (
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
            onSelect={(document) => void handleSelectDocument(document)}
          />
        )}
      </div>

      <Drawer
        anchor="right"
        open={viewerOpen && Boolean(selectedDocument)}
        onClose={handleCloseViewer}
        sx={{
          '& .MuiDrawer-paper': {
            width: 'min(80rem, 100vw)',
            maxWidth: '100vw',
          },
        }}
        slotProps={{ paper: { className: 'document-viewer-drawer__paper' } }}
      >
        <DocumentViewer document={selectedDocument} onReindex={onReindex} onClose={handleCloseViewer} />
      </Drawer>
    </section>
  );
}
