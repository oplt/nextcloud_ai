// ─────────────────────────────────────────────────────────────
// API types  –  single source of truth for the frontend
// ─────────────────────────────────────────────────────────────

export type Role = {
  id: string;
  name: string;
  description: string | null;
  is_system: boolean;
  created_at: string;
  updated_at: string;
};

export type UserSummary = {
  id: string;
  username: string;
  email: string | null;
  full_name: string | null;
};

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
  role: Role | null;
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

export type HealthReadiness = {
  status: 'ready' | 'not_ready';
  database: string;
  redis: string;
  broker: string;
  ai_runtime: {
    ready: boolean;
    required?: boolean;
    error?: string | null;
    available_models?: string[];
    missing_models?: string[];
    warmed_capabilities?: string[];
    required_models?: Record<string, string>;
  };
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
  owner_user_id: string | null;
  owner: UserSummary | null;
  created_at: string;
  updated_at: string;
};

export type ConnectorPayload = {
  connector_type?: 'nextcloud' | 'imap';
  display_name: string;
  base_url: string;
  username: string;
  secret: string;
  root_path: string;
  verify_tls?: boolean;
  port?: number | null;
  use_ssl?: boolean;
  search_criteria?: string | null;
  owner_user_id?: string | null;
};

export type ConnectorUpdatePayload = {
  display_name?: string;
  base_url?: string;
  username?: string;
  secret?: string;
  root_path?: string;
  is_active?: boolean;
  status?: string;
  verify_tls?: boolean;
  port?: number | null;
  use_ssl?: boolean;
  search_criteria?: string | null;
  owner_user_id?: string | null;
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
  connector: Connector | null;
  created_at: string;
  updated_at: string;
};

export type DocumentSummary = {
  id: string;
  connector_id: string | null;
  external_id: string | null;
  file_path: string;
  file_name: string;
  file_extension: string | null;
  mime_type: string | null;
  checksum: string | null;
  size_bytes: number | null;
  source_type: string;
  version_tag: string | null;
  source_url: string | null;
  modified_at: string | null;
  sync_status: string;
  sync_error: string | null;
  parse_status: string;
  parse_error: string | null;
  language: string | null;
  page_count: number | null;
  word_count: number | null;
  token_count: number | null;
  indexed_at: string | null;
  classified_at: string | null;
  last_seen_at: string | null;
  is_deleted: boolean;
  owner_external_id: string | null;
  owner_id: string | null;
  permission_scope: string | null;
  allowed_user_ids: string[];
  allowed_group_ids: string[];
  public_link_enabled: boolean;
  acl_json: Record<string, unknown> | null;
  metadata_json: Record<string, unknown> | null;
  intelligence_json: Record<string, unknown> | null;
  ingestion_events_json: Record<string, unknown>[] | null;
  document_type: string;
  document_type_confidence: number;
  document_type_reason: string | null;
  document_type_source: string;
  business_domain: string;
  business_domain_confidence: number;
  business_domain_reason: string | null;
  business_domain_source: string;
  manual_category_override: boolean;
  chunk_count: number;
  signal_counts: Record<string, number>;
  needs_review: boolean;
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
  chunk_type: string;
  embedding_status: string;
  embedding_model: string | null;
  metadata_json: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
};

export type DocumentDetail = DocumentSummary & {
  chunks: DocumentChunk[];
  insights: DocumentInsight[];
  workflow_tasks: WorkflowTask[];
  knowledge_nodes: KnowledgeNode[];
  knowledge_edges: KnowledgeEdge[];
};

export type DocumentInsight = {
  id: string;
  document_id: string;
  insight_type: string;
  title: string | null;
  summary: string | null;
  status: string;
  confidence: number | null;
  owner_label: string | null;
  due_at: string | null;
  payload_json: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
};

export type WorkflowTask = {
  id: string;
  document_id: string | null;
  insight_id: string | null;
  task_type: string;
  queue_name: string;
  title: string;
  description: string | null;
  status: string;
  priority: string;
  owner_label: string | null;
  due_at: string | null;
  completed_at: string | null;
  hook_status: string | null;
  hook_response: string | null;
  hook_last_attempt_at: string | null;
  metadata_json: Record<string, unknown> | null;
  document_file_name?: string | null;
  document_file_path?: string | null;
  document_connector_id?: string | null;
  created_at: string;
  updated_at: string;
};

export type KnowledgeNode = {
  id: string;
  node_type: string;
  label: string;
  external_key: string;
  document_id: string | null;
  metadata_json: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
};

export type KnowledgeEdge = {
  id: string;
  source_node_id: string;
  target_node_id: string;
  document_id: string | null;
  relation_type: string;
  weight: number;
  metadata_json: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
};

export type IntelligenceOpenTask = WorkflowTask & {
  document_file_name: string | null;
  document_file_path: string | null;
  document_connector_id: string | null;
};

export type IntelligenceSpotlightDocument = {
  document_id: string;
  file_name: string;
  file_path: string;
  connector_id: string;
  classification: string | null;
  insight_types: string[];
  open_task_count: number;
  queue_names: string[];
  modified_at: string | null;
  updated_at: string;
};

export type IntelligenceOverview = {
  intelligence_feature_enabled?: boolean;
  wedge: string;
  document_type_counts: Record<string, number>;
  task_status_counts: Record<string, number>;
  queue_counts: Record<string, number>;
  open_tasks: IntelligenceOpenTask[];
  spotlight_documents: IntelligenceSpotlightDocument[];
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
  generation_metadata_json?: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
};

export type ChatSessionSummary = {
  id: string;
  user_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  /** Server-managed session memory (goals, locks, facts); not document evidence. */
  memory_json?: Record<string, unknown> | null;
};

export type ChatSessionDetail = ChatSessionSummary & {
  messages: ChatMessage[];
  /** IDs of documents pinned as active context for this session. */
  active_context_document_ids?: string[];
  active_context_documents?: ChatActiveContextDocument[];
};

export type ChatAskRequest = {
  question: string;
  session_id?: string | null;
  top_k?: number;
  parent_message_id?: string | null;
  document_ids?: string[] | null;
  active_context_document_ids?: string[];
  request_id?: string;
  retrieval_filters?: RetrievalFilters;
  clear_session_memory?: boolean;
  focus_lock_document_ids?: string[];
  memory_items_patch?: Array<Record<string, unknown>> | null;
};

export type ChatAskResponse = {
  session_id: string;
  answer: string;
  answer_confidence?: number | null;
  sources: ChatSource[];
  cited_sources?: ChatSource[];
  user_message_id: string;
  assistant_message_id: string;
  parent_message_id?: string | null;
  request_id?: string | null;
  active_context_document_ids?: string[];
  active_context_documents?: ChatActiveContextDocument[];
  conversation_query?: string;
  generation_trace_id: string;
  llm_provider: string;
  llm_model_id: string;
  grounded_prompt_version: string;
  retrieval_settings?: Record<string, unknown>;
  verification?: Record<string, unknown> | null;
  retrieval_debug?: Record<string, unknown> | null;
  memory_applied?: Record<string, unknown> | null;
};

export type ChatMemoryPatchRequest = {
  clear?: boolean;
  focus_lock_document_ids?: string[] | null;
  items?: Array<Record<string, unknown>>;
};

/** Normalized session memory object returned by PATCH /chat/sessions/:id/memory */
export type ChatSessionMemoryJson = Record<string, unknown>;

export type RetrievalFilters = {
  connector_ids?: string[];
  mime_types?: string[];
  path_prefixes?: string[];
  modified_after?: string | null;
  modified_before?: string | null;
  document_types?: string[];
  business_domains?: string[];
  source_types?: string[];
};

export type RetrievalFilterFormState = {
  connector_id: string;
  mime_type: string;
  path_prefix: string;
  modified_after: string;
  modified_before: string;
};

export type DocumentListFilters = {
  query?: string;
  connector_ids?: string[];
  mime_types?: string[];
  path_prefixes?: string[];
  modified_after?: string | null;
  modified_before?: string | null;
  document_type?: string | null;
  business_domain?: string | null;
  parse_status?: string | null;
  source_type?: string | null;
  needs_review?: boolean | null;
  low_confidence?: boolean | null;
};

export type DocumentFilterFormState = {
  query: string;
  connector_id: string;
  mime_type: string;
  path_prefix: string;
  modified_after: string;
  modified_before: string;
  document_type: string;
  business_domain: string;
  parse_status: string;
  needs_review: boolean;
};

export type AuditLog = {
  id: string;
  user_id: string | null;
  action: string;
  resource_type: string;
  resource_id: string | null;
  message: string | null;
  metadata_json: Record<string, unknown> | null;
  user: UserSummary | null;
  created_at: string;
  updated_at: string;
};

export type AuditLogFilters = {
  user_id?: string;
  action?: string;
  resource_type?: string;
  resource_id?: string;
  query?: string;
};

export type CreateUserPayload = {
  username: string;
  email?: string | null;
  full_name?: string | null;
  password: string;
  role_id?: string | null;
  is_superuser?: boolean;
};

export type UpdateUserPayload = {
  full_name?: string | null;
  job_title?: string | null;
  avatar_url?: string | null;
  is_active?: boolean | null;
  role_id?: string | null;
};
