import { useCallback, useEffect, useMemo, useState } from 'react';

import type { DocumentDetail, DocumentSummary } from '../types/api';
import {
  DocumentTable,
  type DocumentSortColumn,
  type SortDirection,
} from '../components/DocumentTable';
import { DocumentViewer } from '../components/DocumentViewer';
import { getDocumentTypeLabel } from '../utils/documentDisplay';

const ROWS_PER_PAGE = 20;

type DocumentsPageProps = {
  documents: DocumentSummary[];
  selectedDocumentId: string | null;
  selectedDocument: DocumentDetail | null;
  onSelect:   (document: DocumentSummary) => Promise<void>;
  onReindex:  (documentId: string) => Promise<void>;
};

export function DocumentsPage({
  documents,
  selectedDocumentId,
  selectedDocument,
  onSelect,
  onReindex,
}: DocumentsPageProps) {
  const [sortColumn, setSortColumn]       = useState<DocumentSortColumn>('updated');
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc');
  const [currentPage, setCurrentPage]     = useState(1);

  const sortedDocuments = useMemo(() => {
    return [...documents].sort((a, b) => {
      const dir = sortDirection === 'asc' ? 1 : -1;

      if (sortColumn === 'updated') {
        const at = a.modified_at ? new Date(a.modified_at).getTime() : Number.NEGATIVE_INFINITY;
        const bt = b.modified_at ? new Date(b.modified_at).getTime() : Number.NEGATIVE_INFINITY;
        if (at !== bt) return (at - bt) * dir;
        return a.file_name.localeCompare(b.file_name) * dir;
      }

      if (sortColumn === 'type') {
        const c = getDocumentTypeLabel(a).localeCompare(getDocumentTypeLabel(b));
        if (c !== 0) return c * dir;
        return a.file_name.localeCompare(b.file_name) * dir;
      }

      if (sortColumn === 'status') {
        const c = a.parse_status.localeCompare(b.parse_status);
        if (c !== 0) return c * dir;
        return a.file_name.localeCompare(b.file_name) * dir;
      }

      // default: name
      return a.file_name.localeCompare(b.file_name) * dir;
    });
  }, [documents, sortColumn, sortDirection]);

  const totalPages = Math.max(1, Math.ceil(sortedDocuments.length / ROWS_PER_PAGE));

  // Clamp page when total changes
  useEffect(() => {
    setCurrentPage((p) => Math.min(p, totalPages));
  }, [totalPages]);

  // Reset to page 1 on sort change
  useEffect(() => {
    setCurrentPage(1);
  }, [sortColumn, sortDirection]);

  const paginatedDocuments = useMemo(() => {
    const start = (currentPage - 1) * ROWS_PER_PAGE;
    return sortedDocuments.slice(start, start + ROWS_PER_PAGE);
  }, [currentPage, sortedDocuments]);

  const handleSort = useCallback(
    (column: DocumentSortColumn) => {
      if (column === sortColumn) {
        setSortDirection((d) => (d === 'asc' ? 'desc' : 'asc'));
      } else {
        setSortColumn(column);
        setSortDirection(column === 'updated' ? 'desc' : 'asc');
      }
    },
    [sortColumn],
  );

  return (
    <section className="split-layout split-layout--wide">
      <DocumentTable
        documents={paginatedDocuments}
        totalDocuments={sortedDocuments.length}
        selectedDocumentId={selectedDocumentId}
        sortColumn={sortColumn}
        sortDirection={sortDirection}
        currentPage={currentPage}
        totalPages={totalPages}
        rowsPerPage={ROWS_PER_PAGE}
        onPageChange={setCurrentPage}
        onSort={handleSort}
        onSelect={(doc) => void onSelect(doc)}
      />
      <DocumentViewer document={selectedDocument} onReindex={onReindex} />
    </section>
  );
}
