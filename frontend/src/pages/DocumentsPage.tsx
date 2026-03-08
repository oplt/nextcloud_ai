import { useEffect, useMemo, useState } from 'react';

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
  onSelect: (document: DocumentSummary) => Promise<void>;
  onReindex: (documentId: string) => Promise<void>;
};

export function DocumentsPage({
  documents,
  selectedDocumentId,
  selectedDocument,
  onSelect,
  onReindex,
}: DocumentsPageProps) {
  const [sortColumn, setSortColumn] = useState<DocumentSortColumn>('updated');
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc');
  const [currentPage, setCurrentPage] = useState(1);

  const sortedDocuments = useMemo(() => {
    const sorted = [...documents].sort((left, right) => {
      const direction = sortDirection === 'asc' ? 1 : -1;

      if (sortColumn === 'updated') {
        const leftTime = left.modified_at ? new Date(left.modified_at).getTime() : Number.NEGATIVE_INFINITY;
        const rightTime = right.modified_at ? new Date(right.modified_at).getTime() : Number.NEGATIVE_INFINITY;
        if (leftTime !== rightTime) {
          return (leftTime - rightTime) * direction;
        }
        return left.file_name.localeCompare(right.file_name) * direction;
      }

      if (sortColumn === 'type') {
        const typeComparison = getDocumentTypeLabel(left).localeCompare(getDocumentTypeLabel(right));
        if (typeComparison !== 0) {
          return typeComparison * direction;
        }
        return left.file_name.localeCompare(right.file_name) * direction;
      }

      if (sortColumn === 'status') {
        const statusComparison = left.parse_status.localeCompare(right.parse_status);
        if (statusComparison !== 0) {
          return statusComparison * direction;
        }
        return left.file_name.localeCompare(right.file_name) * direction;
      }

      return left.file_name.localeCompare(right.file_name) * direction;
    });

    return sorted;
  }, [documents, sortColumn, sortDirection]);

  const totalPages = Math.max(1, Math.ceil(sortedDocuments.length / ROWS_PER_PAGE));

  useEffect(() => {
    setCurrentPage((page) => Math.min(page, totalPages));
  }, [totalPages]);

  useEffect(() => {
    setCurrentPage(1);
  }, [sortColumn, sortDirection]);

  const paginatedDocuments = useMemo(() => {
    const start = (currentPage - 1) * ROWS_PER_PAGE;
    return sortedDocuments.slice(start, start + ROWS_PER_PAGE);
  }, [currentPage, sortedDocuments]);

  const handleSort = (column: DocumentSortColumn) => {
    if (column === sortColumn) {
      setSortDirection((currentDirection) => (currentDirection === 'asc' ? 'desc' : 'asc'));
      return;
    }

    setSortColumn(column);
    setSortDirection(column === 'updated' ? 'desc' : 'asc');
  };

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
        onSelect={(document) => void onSelect(document)}
      />
      <DocumentViewer document={selectedDocument} onReindex={onReindex} />
    </section>
  );
}
