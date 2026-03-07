import type { DocumentDetail, DocumentSummary } from '../types/api';
import { DocumentTable } from '../components/DocumentTable';
import { DocumentViewer } from '../components/DocumentViewer';

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
  return (
    <section className="split-layout split-layout--wide">
      <DocumentTable documents={documents} selectedDocumentId={selectedDocumentId} onSelect={(document) => void onSelect(document)} />
      <DocumentViewer document={selectedDocument} onReindex={onReindex} />
    </section>
  );
}
