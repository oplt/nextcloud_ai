import { useMemo, useState } from "react";

import Alert from "@mui/material/Alert";
import CardActionArea from "@mui/material/CardActionArea";

import { AppCard } from "../components/ui/AppCard";
import { EmptyState } from "../components/ui/EmptyState";
import { StatusBadge } from "../components/ui/StatusBadge";
import { statusToneFromValue } from "../components/ui/statusTone";
import { TooltipInfo } from "../components/ui/TooltipInfo";
import type {
  DocumentDetail,
  IntelligenceOverview,
  WorkflowTask,
} from "../types/api";
import {
  formatConfidence,
  formatTaxonomyLabel,
  getBusinessDomainLabel,
  getDocumentTypeLabel,
  formatDateTime,
} from "../utils/documentDisplay";

type IntelligencePageProps = {
  overview: IntelligenceOverview | null;
  loading: boolean;
  error: string | null;
  selectedDocument: DocumentDetail | null;
  onSelectDocument: (documentId: string) => Promise<void>;
};

type TaskFilter =
    | "all"
    | "compliance"
    | "contract"
    | "meeting"
    | "high_priority"
    | "due_soon";

const DOCUMENT_TYPE_ORDER = [
  "contract",
  "invoice_finance",
  "email_correspondence",
  "policy_document",
  "legal",
  "compliance",
  "meeting_notes",
  "technical_documentation",
  "hr",
  "sales_proposal",
  "project_document",
  "support_operations",
  "general_knowledge",
  "unclassified",
];

const BUSINESS_DOMAIN_ORDER = [
  "legal",
  "finance",
  "hr",
  "engineering",
  "operations",
  "sales",
  "procurement",
  "compliance",
  "customer_support",
  "management",
  "unknown",
];

const DOCUMENT_TYPE_ALIASES: Record<string, string> = {
  email: "email_correspondence",
  meeting: "meeting_notes",
  policy: "policy_document",
  general: "general_knowledge",
};

const TASK_FILTERS: Array<{ key: TaskFilter; label: string }> = [
  { key: "all", label: "All" },
  { key: "compliance", label: "Compliance" },
  { key: "contract", label: "Contract" },
  { key: "meeting", label: "Meeting" },
  { key: "high_priority", label: "High priority" },
  { key: "due_soon", label: "Due soon" },
];

function formatKey(value: string): string {
  return value.replace(/[_-]+/g, " ");
}

function currentDocumentType(value: string | null | undefined): string {
  if (!value) return "unclassified";
  return DOCUMENT_TYPE_ALIASES[value] ?? value;
}

function renderTaskMeta(task: WorkflowTask) {
  const bits = [
    task.queue_name,
    task.priority,
    task.owner_label,
    task.due_at ? `due ${formatDateTime(task.due_at)}` : null,
  ].filter(Boolean);
  return bits.join(" • ");
}

type ProvenancePayload = {
  methods?: string[];
  evidence_tier?: string;
  notes?: string;
};

function readProvenance(
    payload: Record<string, unknown> | null | undefined,
): ProvenancePayload | null {
  const raw = payload?.provenance;
  if (!raw || typeof raw !== "object") {
    return null;
  }
  return raw as ProvenancePayload;
}

function formatProvenanceSummary(
    payload: Record<string, unknown> | null | undefined,
): string | null {
  const p = readProvenance(payload);
  if (!p?.evidence_tier) {
    return null;
  }
  const tier = formatKey(p.evidence_tier);
  const methods = (p.methods ?? []).slice(0, 4).map((m) => formatKey(m));
  const tail = methods.length
      ? ` · ${methods.join(", ")}${(p.methods?.length ?? 0) > 4 ? "…" : ""}`
      : "";
  return `Evidence: ${tier}${tail}`;
}

function taskPresentation(task: WorkflowTask): string | null {
  const meta = task.metadata_json;
  if (!meta || typeof meta !== "object") {
    return null;
  }
  const p = (meta as { presentation?: string }).presentation;
  return typeof p === "string" ? p : null;
}

function taskMatchesNeedle(task: WorkflowTask, needle: string): boolean {
  const haystack = [
    task.queue_name,
    task.title,
    task.description,
    task.document_file_name,
  ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
  return haystack.includes(needle);
}

function taskConfidence(task: WorkflowTask): number | null {
  if (typeof task.confidence_score === "number" && !Number.isNaN(task.confidence_score)) {
    return task.confidence_score > 1 ? Math.round(task.confidence_score) : Math.round(task.confidence_score * 100);
  }

  const meta = task.metadata_json;
  if (!meta || typeof meta !== "object") {
    return null;
  }

  const raw =
      (meta as { confidence?: unknown }).confidence ??
      (meta as { confidence_score?: unknown }).confidence_score;

  if (typeof raw !== "number" || Number.isNaN(raw)) {
    return null;
  }

  return raw > 1 ? Math.round(raw) : Math.round(raw * 100);
}

function confidenceLabel(score: number | null): string {
  if (score === null) return "Unscored";
  if (score >= 80) return "High trust";
  if (score >= 55) return "Needs review";
  return "Weak signal";
}

function confidenceClass(score: number | null): string {
  if (score === null) return "neutral";
  if (score >= 80) return "success";
  if (score >= 55) return "warning";
  return "danger";
}

function taskReviewReason(task: WorkflowTask): string {
  if (task.reason) {
    return task.reason;
  }
  const presentation = taskPresentation(task);
  const description = (task.description ?? "").trim();
  if (presentation === "suggestion") {
    return (
        description ||
        "The system found a possible issue, but it has not been verified. Treat this as a review prompt, not a confirmed finding."
    );
  }
  return (
      description ||
      "This item was generated from indexed document signals and needs human confirmation before it becomes assigned work."
  );
}

function taskEvidenceLabel(task: WorkflowTask): string {
  if (task.evidence_method || task.confidence_level) {
    return `Evidence: ${formatKey(task.confidence_level ?? "unscored")} · ${formatKey(task.evidence_method ?? "unknown method")}`;
  }
  const provLine = formatProvenanceSummary(task.metadata_json);
  if (provLine) return provLine;
  if (taskPresentation(task) === "suggestion") {
    return "Evidence: weak signal · review source before acting";
  }
  return "Evidence: source-linked signal · verify details before approval";
}

function taskDecisionLabel(task: WorkflowTask): string {
  if (task.recommended_action) {
    return task.recommended_action;
  }
  if (taskPresentation(task) === "suggestion") {
    return "Decide whether this should become real work";
  }
  return "Confirm scope, owner, and next action";
}

function acceptanceProgress(task: WorkflowTask): string {
  const criteria = task.acceptance_criteria ?? [];
  if (criteria.length === 0) {
    return "No checklist";
  }
  const completed = criteria.filter((item) => item.completed === true).length;
  return `${completed}/${criteria.length} criteria`;
}

function isHighPriority(task: WorkflowTask): boolean {
  const priority = task.priority?.toLowerCase() ?? "";
  return ["urgent", "high", "critical"].includes(priority);
}

function isDueSoon(task: WorkflowTask): boolean {
  if (!task.due_at) {
    return false;
  }

  const due = new Date(task.due_at).getTime();
  if (Number.isNaN(due)) {
    return false;
  }

  const now = Date.now();
  const sevenDays = 7 * 24 * 60 * 60 * 1000;
  return due <= now + sevenDays;
}

function filterTasks(
    tasks: WorkflowTask[],
    activeFilter: TaskFilter,
): WorkflowTask[] {
  switch (activeFilter) {
    case "compliance":
      return tasks.filter((task) => taskMatchesNeedle(task, "compliance"));
    case "contract":
      return tasks.filter((task) => taskMatchesNeedle(task, "contract"));
    case "meeting":
      return tasks.filter((task) => taskMatchesNeedle(task, "meeting"));
    case "high_priority":
      return tasks.filter(isHighPriority);
    case "due_soon":
      return tasks.filter(isDueSoon);
    case "all":
    default:
      return tasks;
  }
}

function orderedBreakdown(
    counts: Record<string, number>,
    order: string[],
    normalizeKey: (value: string) => string = (value) => value,
) {
  const normalized = Object.entries(counts).reduce<Record<string, number>>(
      (acc, [key, count]) => {
        const currentKey = normalizeKey(key);
        acc[currentKey] = (acc[currentKey] ?? 0) + count;
        return acc;
      },
      {},
  );

  return Object.entries(normalized)
      .map(([key, count]) => ({ key, count }))
      .sort((a, b) => {
        const ai = order.indexOf(a.key);
        const bi = order.indexOf(b.key);
        if (ai !== -1 || bi !== -1) {
          return (
              (ai === -1 ? Number.MAX_SAFE_INTEGER : ai) -
              (bi === -1 ? Number.MAX_SAFE_INTEGER : bi)
          );
        }
        return b.count - a.count || a.key.localeCompare(b.key);
      });
}

export function IntelligencePage({
                                   overview,
                                   loading,
                                   error,
                                   selectedDocument,
                                   onSelectDocument,
                                 }: IntelligencePageProps) {
  const [activeTaskFilter, setActiveTaskFilter] = useState<TaskFilter>("all");

  const visibleOpenTasks = useMemo(
      () => filterTasks(overview?.open_tasks ?? [], activeTaskFilter),
      [overview?.open_tasks, activeTaskFilter],
  );

  const queueHealth = useMemo(() => {
    const openTasks = overview?.open_tasks ?? [];
    return {
      pendingReview: openTasks.length,
      highPriority: openTasks.filter(isHighPriority).length,
      dueSoon: openTasks.filter(isDueSoon).length,
      suggestions: openTasks.filter(
          (task) => taskPresentation(task) === "suggestion",
      ).length,
    };
  }, [overview?.open_tasks]);

  if (error) {
    return (
        <AppCard component="section" className="card card--panel detail-card">
          <Alert severity="error" className="page-alert">
            {error}
          </Alert>
        </AppCard>
    );
  }

  if (loading) {
    return (
        <AppCard component="section" className="card card--panel detail-card">
          <Alert
              severity="info"
              className="page-alert"
              role="status"
              aria-live="polite"
          >
            Loading intelligence overview…
          </Alert>
        </AppCard>
    );
  }

  if (!overview) {
    return (
        <AppCard component="section" className="card card--panel detail-card">
          <EmptyState
              title="No intelligence data yet"
              description="Sync or reindex documents to generate structured outputs."
              className="workflow-tasks-empty"
          />
        </AppCard>
    );
  }

  if (overview.intelligence_feature_enabled === false) {
    return (
        <AppCard component="section" className="card card--panel detail-card">
          <Alert severity="info" className="page-alert" role="status">
            Product intelligence is disabled for this deployment. Chat and
            document search are unaffected.
          </Alert>
        </AppCard>
    );
  }

  const documentTypeStats = Object.entries(overview.document_type_counts)
      .map(([key, count]) => ({
        label: formatKey(currentDocumentType(key)),
        value: count,
        group: "Document type",
      }))
      .slice(0, 4);

  const queueStats = Object.entries(overview.queue_counts)
      .map(([key, count]) => ({
        label: `${formatKey(key)} queue`,
        value: count,
        group: "Workflow queue",
      }))
      .slice(0, 3);

  const statEntries = [...documentTypeStats, ...queueStats].slice(0, 6);
  const documentTypeBreakdown = orderedBreakdown(
      overview.document_type_counts,
      DOCUMENT_TYPE_ORDER,
      currentDocumentType,
  );
  const businessDomainBreakdown = orderedBreakdown(
      overview.business_domain_counts ?? {},
      BUSINESS_DOMAIN_ORDER,
  );
  const selectedDocumentType = selectedDocument
      ? currentDocumentType(selectedDocument.document_type)
      : "unclassified";
  const selectedDocumentForDisplay = selectedDocument
      ? { ...selectedDocument, document_type: selectedDocumentType }
      : null;

  return (
      <div className="intelligence-stack">
        <section
            className="intelligence-command-bar"
            aria-label="Intelligence command summary"
        >
          <div>
            <span className="eyebrow">AI review queue</span>
            <h2>
              Review source-linked work
              <TooltipInfo title="Tasks are queued by default; review status and checklist live in task metadata." />
            </h2>
            <p>
              Triage, verify, assign.
            </p>
          </div>

          <div
              className="intelligence-command-summary"
              aria-label="Workflow summary"
          >
            <div className="intelligence-command-summary__group">
            <span className="summary-pill summary-pill--review">
              {queueHealth.pendingReview} pending review
            </span>
              <span className="summary-pill summary-pill--danger">
              {queueHealth.highPriority} high priority
            </span>
              <span className="summary-pill summary-pill--warning">
              {queueHealth.dueSoon} due soon
            </span>
              <span className="summary-pill summary-pill--suggestion">
              {queueHealth.suggestions} suggestions
            </span>
            </div>

            <div className="intelligence-command-summary__group intelligence-command-summary__group--secondary">
              {statEntries.map((entry) => (
                  <span
                      key={entry.label}
                      className="summary-pill summary-pill--neutral"
                  >
                {entry.value} {entry.label}
              </span>
              ))}
            </div>
          </div>
        </section>

        <section className="split-layout intelligence-layout">
          <div className="documents-panel">
            <AppCard
                component="section"
                className="card card--panel table-card intelligence-classification-card"
            >
              <header className="panel-header">
                <div>
                  <h3>Indexed document map</h3>
                  <p className="filter-card__meta">
                    A lightweight map of indexed content. Use it for filtering and
                    orientation, not as a final business classification.
                  </p>
                </div>
                <span className="panel-header__count">
                {documentTypeBreakdown.reduce(
                    (sum, entry) => sum + entry.count,
                    0,
                )}
              </span>
              </header>

              <div className="intelligence-classification-grid">
                <div className="intelligence-classification-column">
                  <span className="eyebrow">Document types</span>
                  <div className="intelligence-node-cloud">
                    {documentTypeBreakdown.length === 0 ? (
                        <span className="pill pill--neutral">
                      No classified documents
                    </span>
                    ) : (
                        documentTypeBreakdown.map((entry) => (
                            <span key={entry.key} className="pill pill--neutral">
                        {entry.count} {formatTaxonomyLabel(entry.key)}
                      </span>
                        ))
                    )}
                  </div>
                </div>

                <div className="intelligence-classification-column">
                  <span className="eyebrow">Business domains</span>
                  <div className="intelligence-node-cloud">
                    {businessDomainBreakdown.length === 0 ? (
                        <span className="pill pill--neutral">No domains yet</span>
                    ) : (
                        businessDomainBreakdown.map((entry) => (
                            <span key={entry.key} className="pill pill--neutral">
                        {entry.count} {formatTaxonomyLabel(entry.key)}
                      </span>
                        ))
                    )}
                  </div>
                </div>
              </div>
            </AppCard>

            <AppCard
                component="section"
                className="card card--panel table-card workflow-tasks-card"
            >
              <header className="panel-header workflow-tasks-header">
                <div>
                  <h3>Review queue</h3>
                  <p className="filter-card__meta">
                    Each card is a proposed action from document signals. Verify
                    the source before assigning, dismissing, or converting it into
                    work.
                  </p>
                </div>
                <span className="panel-header__count">
                {visibleOpenTasks.length}
              </span>
              </header>

              <div
                  className="task-filter-tabs"
                  role="tablist"
                  aria-label="Filter workflow tasks"
              >
                {TASK_FILTERS.map((filter) => (
                    <button
                        key={filter.key}
                        type="button"
                        className={
                          filter.key === activeTaskFilter
                              ? "task-filter-tab task-filter-tab--active"
                              : "task-filter-tab"
                        }
                        onClick={() => setActiveTaskFilter(filter.key)}
                    >
                      {filter.label}
                    </button>
                ))}
              </div>

              <div className="workflow-tasks-scroll">
                {visibleOpenTasks.length === 0 ? (
                    <EmptyState
                        title="No tasks for this filter"
                        description="Try a different queue filter."
                        className="workflow-tasks-empty"
                    />
                ) : (
                    <div className="intelligence-task-list">
                      {visibleOpenTasks.map((task) => {
                        const confidence = taskConfidence(task);

                        return (
                            <AppCard
                                key={task.id}
                                className="card card--row intelligence-task-card"
                            >
                              <CardActionArea
                                  onClick={() =>
                                      task.document_id &&
                                      void onSelectDocument(task.document_id)
                                  }
                                  sx={{ p: 2, borderRadius: "inherit" }}
                              >
                                <div className="intelligence-task-card__header">
                                  <div className="intelligence-task-card__title">
                                    <strong>{task.title}</strong>
                                    {task.document_file_name ? (
                                        <span className="eyebrow">
                                          Source: {task.document_file_name}
                                        </span>
                                    ) : null}
                                  </div>
                                  <span className="intelligence-task-card__pills">
                                    {task.review_status ? (
                                        <StatusBadge
                                            label={formatKey(task.review_status)}
                                            tone={statusToneFromValue(task.review_status)}
                                        />
                                    ) : null}
                                    <StatusBadge
                                        label={confidenceLabel(confidence)}
                                        tone={confidenceClass(confidence) === "danger" ? "danger" : confidenceClass(confidence) === "warning" ? "warning" : confidenceClass(confidence) === "success" ? "success" : "neutral"}
                                    />
                                    <StatusBadge
                                        label={formatKey(task.priority)}
                                        tone={statusToneFromValue(task.priority)}
                                    />
                                    {task.blocked_by_task_ids?.length ? (
                                        <StatusBadge
                                            label={`blocked by ${task.blocked_by_task_ids.length}`}
                                            tone="warning"
                                        />
                                    ) : null}
                            </span>
                                </div>
                                <p>
                                  <strong>Why it appeared:</strong>{" "}
                                  {taskReviewReason(task)}
                                </p>
                                <small>
                                  <strong>Review decision:</strong>{" "}
                                  {taskDecisionLabel(task)}
                                </small>
                                <small>{renderTaskMeta(task)}</small>
                                <small className="filter-card__meta intelligence-task-card__evidence">
                                  {taskEvidenceLabel(task)}
                                </small>
                                <small>
                                  <strong>Checklist:</strong> {acceptanceProgress(task)}
                                </small>
                                <div
                                    className="intelligence-task-card__actions"
                                    aria-label="Suggested review actions"
                                >
                                  <span>Inspect source</span>
                                  <span>Approve / assign</span>
                                  <span>Dismiss weak signal</span>
                                </div>
                              </CardActionArea>
                            </AppCard>
                        );
                      })}
                    </div>
                )}
              </div>
            </AppCard>
          </div>

          <AppCard
              component="section"
              className="card card--panel detail-card intelligence-detail"
              sx={{
                maxHeight: "calc(100vh - 2.5rem)",
                overflowY: "scroll",
                overflowX: "hidden",
                scrollbarGutter: "stable",
              }}
          >
            {selectedDocumentForDisplay ? (
                <>
                  <header className="panel-header">
                    <div>
                      <span className="eyebrow">Source context</span>
                      <h3>{selectedDocumentForDisplay.file_name}</h3>
                      <p className="detail-focus__path">
                        {selectedDocumentForDisplay.file_path}
                      </p>
                      <div className="detail-focus__badges">
                    <span className="pill">
                      {getDocumentTypeLabel(selectedDocumentForDisplay)}
                    </span>
                        <span className="pill pill--neutral">
                      {getBusinessDomainLabel(selectedDocumentForDisplay)}
                    </span>
                        <span className="pill pill--neutral">
                      {formatConfidence(
                          Math.min(
                              selectedDocumentForDisplay.document_type_confidence,
                              selectedDocumentForDisplay.business_domain_confidence,
                          ),
                      )}
                    </span>
                        {selectedDocumentForDisplay.needs_review ? (
                            <span className="pill pill--warning">Needs review</span>
                        ) : null}
                      </div>
                    </div>
                  </header>

                  <section className="intelligence-section">
                    <h4>Classification basis</h4>
                    <div className="intelligence-mini-list">
                      <article className="intelligence-mini-card">
                        <strong>
                          {getDocumentTypeLabel(selectedDocumentForDisplay)} /{" "}
                          {getBusinessDomainLabel(selectedDocumentForDisplay)}
                        </strong>
                        <small>
                          {selectedDocumentForDisplay.document_type_reason ??
                              "No document type basis recorded."}
                        </small>
                        <small>
                          {selectedDocumentForDisplay.business_domain_reason ??
                              "No business-domain basis recorded."}
                        </small>
                      </article>
                    </div>
                  </section>

                  <section className="intelligence-section">
                    <h4>Detected source signals</h4>
                    <div className="intelligence-node-cloud">
                      {Object.entries(selectedDocumentForDisplay.signal_counts).map(
                          ([key, count]) => (
                              <span key={key} className="pill pill--neutral">
                        {count} {formatTaxonomyLabel(key)}
                      </span>
                          ),
                      )}
                    </div>
                  </section>

                  <section className="intelligence-section">
                    <h4>Review notes</h4>
                    {selectedDocumentForDisplay.insights.length === 0 ? (
                        <p className="filter-card__meta">
                          No review notes generated yet.
                        </p>
                    ) : (
                        <div className="intelligence-insight-list">
                          {selectedDocumentForDisplay.insights.map((insight) => {
                            const prov = readProvenance(insight.payload_json);
                            const provLine = formatProvenanceSummary(
                                insight.payload_json,
                            );
                            return (
                                <article
                                    key={insight.id}
                                    className="intelligence-insight-card"
                                >
                                  <div className="intelligence-insight-card__header">
                                    <strong>
                                      {insight.title ?? formatKey(insight.insight_type)}
                                    </strong>
                                    {insight.confidence ? (
                                        <span>
                                {confidenceLabel(
                                    Math.round(insight.confidence * 100),
                                )}
                              </span>
                                    ) : null}
                                  </div>
                                  <p>{insight.summary ?? "No summary available."}</p>
                                  {provLine ? (
                                      <p className="filter-card__meta">{provLine}</p>
                                  ) : null}
                                  {prov?.notes ? (
                                      <p
                                          className="filter-card__meta"
                                          style={{ fontStyle: "italic" }}
                                      >
                                        {prov.notes}
                                      </p>
                                  ) : null}
                                </article>
                            );
                          })}
                        </div>
                    )}
                  </section>

                  <section className="intelligence-section">
                    <h4>Related review items</h4>
                    {selectedDocumentForDisplay.workflow_tasks.length === 0 ? (
                        <p className="filter-card__meta">
                          No review items generated from this document.
                        </p>
                    ) : (
                        <div className="intelligence-mini-list">
                          {selectedDocumentForDisplay.workflow_tasks.map((task) => (
                              <article key={task.id} className="intelligence-mini-card">
                                <strong>{task.title}</strong>
                                <small>{renderTaskMeta(task)}</small>
                              </article>
                          ))}
                        </div>
                    )}
                  </section>

                  <section className="intelligence-section">
                    <h4>Linked entities</h4>
                    {selectedDocumentForDisplay.knowledge_nodes.length === 0 ? (
                        <p className="filter-card__meta">
                          No linked entities generated yet.
                        </p>
                    ) : (
                        <>
                          <div className="intelligence-node-cloud">
                            {selectedDocumentForDisplay.knowledge_nodes
                                .filter((node) => node.node_type !== "document")
                                .map((node) => (
                                    <span
                                        key={node.id}
                                        className={`pill pill--graph-${node.node_type}`}
                                    >
                            {node.label}
                          </span>
                                ))}
                          </div>
                          <div className="intelligence-mini-list">
                            {selectedDocumentForDisplay.knowledge_edges.map(
                                (edge) => {
                                  const source =
                                      selectedDocumentForDisplay.knowledge_nodes.find(
                                          (node) => node.id === edge.source_node_id,
                                      );
                                  const target =
                                      selectedDocumentForDisplay.knowledge_nodes.find(
                                          (node) => node.id === edge.target_node_id,
                                      );
                                  const edgeProv = formatProvenanceSummary(
                                      edge.metadata_json,
                                  );
                                  return (
                                      <article
                                          key={edge.id}
                                          className="intelligence-mini-card"
                                      >
                                        <strong>{formatKey(edge.relation_type)}</strong>
                                        <small>
                                          {source?.label ?? "document"} →{" "}
                                          {target?.label ?? "unknown"}
                                        </small>
                                        {edgeProv ? (
                                            <small className="filter-card__meta">
                                              {edgeProv}
                                            </small>
                                        ) : null}
                                      </article>
                                  );
                                },
                            )}
                          </div>
                        </>
                    )}
                  </section>
                </>
            ) : (
                <EmptyState
                    title="Select a review item"
                    description="Inspect source, evidence, signals, and linked entities."
                    className="workflow-tasks-empty"
                />
            )}
          </AppCard>
        </section>
      </div>
  );
}
