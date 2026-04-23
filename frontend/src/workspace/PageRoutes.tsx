import { Navigate } from 'react-router-dom';

import { AdminPage } from '../pages/AdminPage';
import { ConnectorsPage } from '../pages/ConnectorsPage';
import { DocumentsPage } from '../pages/DocumentsPage';
import { IntelligencePage } from '../pages/IntelligencePage';
import { JobsPage } from '../pages/JobsPage';
import { OverviewPage } from '../pages/OverviewPage';
import { useWorkspace } from './WorkspaceContext';

export function OverviewRoute() {
  const w = useWorkspace();
  return (
    <OverviewPage
      user={w.user}
      connectors={w.connectors}
      documents={w.documents}
      sessions={w.sessions}
      activeSession={w.activeSessionView}
      loading={w.busy}
      workspaceLoading={w.workspaceDataLoading}
      workspaceError={w.workspaceDataError}
      chatError={w.chatAskError}
      chatFilters={w.chatFilters}
      availableMimeTypes={w.availableMimeTypes}
      onSelectSession={w.handleSelectSession}
      onAsk={w.handleAsk}
      onNewChat={w.handleNewChat}
      onDeleteSessions={w.handleDeleteSessions}
      onChatFilterChange={(patch) => w.setChatFilters((current) => ({ ...current, ...patch }))}
      onResetChatFilters={w.resetChatFilters}
    />
  );
}

export function ConnectorsRoute() {
  const w = useWorkspace();
  return (
    <ConnectorsPage
      connectors={w.connectors}
      listLoading={w.workspaceDataLoading}
      listError={w.workspaceDataError}
      onCreate={w.handleCreate}
      onDelete={w.handleDelete}
      onTest={w.handleTestConnector}
      onSync={w.handleSyncConnector}
      onToggleActive={w.handleToggleConnectorActive}
    />
  );
}

export function DocumentsRoute() {
  const w = useWorkspace();
  return (
    <DocumentsPage
      documents={w.documents}
      connectors={w.connectors}
      selectedDocument={w.selectedDocument}
      selectedDocumentId={w.selectedDocumentId}
      viewLoading={w.documentsViewLoading}
      viewError={w.documentsViewError}
      onSelect={w.handleSelectDocument}
      onReindex={w.handleReindexDocument}
    />
  );
}

export function IntelligenceRoute() {
  const w = useWorkspace();
  return (
    <IntelligencePage
      overview={w.intelligenceOverview}
      loading={w.intelligenceLoading}
      error={w.intelligenceError}
      connectors={w.connectors}
      selectedDocument={w.selectedDocument}
      onSelectDocument={w.handleSelectDocumentById}
    />
  );
}

export function JobsRoute() {
  const w = useWorkspace();
  return (
    <JobsPage
      jobs={w.jobs}
      connectors={w.connectors}
      loading={w.jobsLoading}
      refreshing={w.jobsRefreshing}
      error={w.jobsError}
      lastUpdatedAt={w.jobsLastUpdatedAt}
      onRefresh={async () => {
        await w.loadJobs();
      }}
      onRetry={w.handleRetryJob}
    />
  );
}

export function AdminRoute() {
  const w = useWorkspace();
  if (!w.isAdmin) {
    return <Navigate to="/" replace />;
  }
  return (
    <AdminPage
      users={w.users}
      roles={w.roles}
      connectors={w.connectors}
      auditLogs={w.auditLogs}
      loading={w.busy || w.adminDataLoading}
      dataError={w.adminDataError}
      onCreateUser={w.handleCreateUser}
      onUpdateUser={w.handleUpdateUser}
      onAssignConnectorOwner={w.handleAssignConnectorOwner}
      onSearchAuditLogs={w.handleSearchAuditLogs}
      onRefresh={w.loadAdminData}
    />
  );
}
