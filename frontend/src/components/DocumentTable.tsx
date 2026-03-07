import type { DocumentSummary } from '../types/api';

type DocumentTableProps = {
  documents: DocumentSummary[];
  selectedDocumentId: string | null;
  onSelect: (document: DocumentSummary) => void;
};

export function DocumentTable({ documents, selectedDocumentId, onSelect }: DocumentTableProps) {
  return (
    <div className="card table-card">
      <header className="panel-header">
        <h3>Documents</h3>
        <span>{documents.length}</span>
      </header>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Status</th>
              <th>Updated</th>
            </tr>
          </thead>
          <tbody>
            {documents.map((document) => (
              <tr
                key={document.id}
                className={selectedDocumentId === document.id ? 'is-selected' : ''}
                onClick={() => onSelect(document)}
              >
                <td>
                  <strong>{document.file_name}</strong>
                  <small>{document.file_path}</small>
                </td>
                <td>
                  <span className={`pill pill--${document.parse_status}`}>{document.parse_status}</span>
                </td>
                <td>{document.modified_at ? new Date(document.modified_at).toLocaleString() : 'Unknown'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
