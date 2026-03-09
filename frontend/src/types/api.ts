// ─────────────────────────────────────────────────────────────
// API types  –  single source of truth for the frontend
// ─────────────────────────────────────────────────────────────

export type User = {
  id: string;
  auth_provider: string;
  external_subject: string | null;
  username: string;
  email: string | null;
  full_name: string | null;
  nextcloud_base_url: string | null;
  last_login_at: string | null;
  is_active: boolean;
  is_superuser: boolean;
  job_title: string | null;
  avatar_url: string | null;
  created_at: string;
  updated_at: string;
};

export type AuthSession = {
  expires_in: number;
  user: User;
};

export type CsrfTokenResponse = {
  csrf_token: string;
};

export type Connector = {
  id: string;
  connector_type: string;
  display_name: string;
  base_url: string;
  username: string;
  root_path: string;
  is_active: boolean;
  status: string;
  last_sync_at: string | null;
  last_error: string | null;
  metadata_json: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
};

export type ConnectorPayload = {
  display_name: string;
  base_url: string;
  username: string;
  secret: string;
  root_path: string;
  verify_tls?: boolean;
};

export type ConnectorUpdatePayload = {
  display_name?: string;
  username?: string;
  secret?: string;
  root_path?: string;
  is_active?: boolean;
  status?: string;
  verify_tls?: boolean;
};

export type SyncJob = {
  id: string;
  connector_id: string;
  requested_by_id: string | null;
  job_key: string;
  worker_task_id: string | null;
  job_type: string;
  status: string;
  retry_count: number;
  progress_total: number | null;
  progress_completed: number | null;
  started_at: string | null;
  completed_at: string | null;
  error_message: string | null;
  payload_json: Record<string, unknown> | null;
  result_json: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
};

export type DocumentSummary = {
  id: string;
  connector_id: string;
  external_id: string;
  file_path: string;
  file_name: string;
  mime_type: string | null;
  checksum: string | null;
  size_bytes: number | null;
  version_tag: string | null;
  source_url: string | null;
  modified_at: string | null;
  sync_status: string;
  sync_error: string | null;
  parse_status: string;
  parse_error: string | null;
  indexed_at: string | null;
  last_seen_at: string | null;
  is_deleted: boolean;
  owner_external_id: string | null;
  allowed_user_ids: string[];
  allowed_group_ids: string[];
  public_link_enabled: boolean;
  acl_json: Record<string, unknown> | null;
  metadata_json: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
};

export type DocumentChunk = {
  id: string;
  document_id: string;
  chunk_index: number;
  content: string;
  token_count: number | null;
  char_start: number | null;
  char_end: number | null;
  page_number: number | null;
  section_title: string | null;
  heading_path: string | null;
  content_hash: string | null;
  metadata_json: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
};

export type DocumentDetail = DocumentSummary & {
  chunks: DocumentChunk[];
};

export type ChatSource = {
  chunk_id: string;
  document_id: string;
  file_name: string;
  file_path: string;
  page_number: number | null;
  section_title: string | null;
  heading_path?: string | null;
  snippet: string;
  distance: number;
  score: number;
};

/** Canonical type for documents in the active chat context. */
export type ChatActiveContextDocument = {
  document_id: string;
  file_name: string;
  file_path: string;
};

/**
 * Alias kept for backward-compat with older page components.
 * Prefer `ChatActiveContextDocument` in new code.
 */
export type ActiveContextDocument = ChatActiveContextDocument;

export type ChatMessage = {
  id: string;
  session_id: string;
  role: string;
  content: string;
  citations_json: Array<Record<string, unknown>> | null;
  model_name: string | null;
  created_at: string;
  updated_at: string;
};

export type ChatSessionSummary = {
  id: string;
  user_id: string;
  title: string;
  created_at: string;
  updated_at: string;
};

export type ChatSessionDetail = ChatSessionSummary & {
  messages: ChatMessage[];
  /** IDs of documents pinned as active context for this session. */
  active_context_document_ids?: string[];
};

export type ChatAskRequest = {
  question: string;
  session_id?: string | null;
  top_k?: number;
  parent_message_id?: string | null;
  active_context_document_ids?: string[];
  request_id?: string;
};

export type ChatAskResponse = {
  session_id: string;
  answer: string;
  sources: ChatSource[];
  cited_sources?: ChatSource[];
  user_message_id: string;
  assistant_message_id: string;
  parent_message_id?: string | null;
  request_id?: string | null;
  active_context_document_ids?: string[];
  active_context_documents?: ChatActiveContextDocument[];
  conversation_query?: string;
};
