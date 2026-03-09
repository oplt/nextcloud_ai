import { useMemo, useState } from 'react';

import type { Connector, SyncJob } from '../types/api';

type JobsPageProps = {
  jobs: SyncJob[];
  connectors: Connector[];
  loading: boolean;
  refreshing: boolean;
  error: string | null;
  lastUpdatedAt: string | null;
  onRefresh: () => Promise<void>;
};

type JobFilter = 'all' | 'active' | 'failed' | 'completed';

function isActiveJob(job: SyncJob): boolean {
  return ['pending', 'queued', 'running', 'processing', 'retrying'].includes(job.status);
}

function isFailedJob(job: SyncJob): boolean {
  return ['failed', 'error'].includes(job.status);
}

function isCompletedJob(job: SyncJob): boolean {
  return ['done', 'completed'].includes(job.status);
}

function formatTimestamp(value: string | null): string {
  if (!value) {
    return 'Not recorded';
  }
  return new Date(value).toLocaleString();
}

function describeJob(job: SyncJob): string {
  if (job.job_type === 'reindex') {
    return 'Full reindex';
  }
  return 'Sync';
}

function getProgressLabel(job: SyncJob): string {
  const total = job.progress_total;
  const completed = job.progress_completed;
  if (typeof total === 'number' && typeof completed === 'number') {
    return `${completed}/${total}`;
  }
  if (typeof completed === 'number') {
    return `${completed} processed`;
  }
  return 'Waiting for progress';
}

function getProgressPercent(job: SyncJob): number {
  const total = job.progress_total ?? 0;
  const completed = job.progress_completed ?? 0;
  if (total <= 0) {
    return isCompletedJob(job) ? 100 : 0;
  }
  return Math.min(100, Math.round((completed / total) * 100));
}

function JobProgressBar({ job }: { job: SyncJob }) {
  const pct = getProgressPercent(job);
  const fillClass =
    isCompletedJob(job)
      ? 'job-progress__fill--done'
      : isFailedJob(job)
        ? 'job-progress__fill--error'
        : '';

  return (
    <div
      className="job-progress"
      role="progressbar"
      aria-valuenow={pct}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={`${pct}% complete`}
    >
      <div className={`job-progress__fill ${fillClass}`.trim()} style={{ width: `${pct}%` }} />
    </div>
  );
}

function EmptyJobs() {
  return (
    <div className="empty-state jobs-empty-state">
      <div className="empty-state-icon" aria-hidden="true">
        <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5">
          <circle cx="10" cy="10" r="8" strokeLinecap="round" />
          <path d="M10 6v4l2.5 2.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </div>
      <span>No jobs available for the current filters.</span>
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <article className="card stat-card">
      <span className="stat-card__label">{label}</span>
      <strong className="stat-card__value">{value}</strong>
    </article>
  );
}

export function JobsPage({
  jobs,
  connectors,
  loading,
  refreshing,
  error,
  lastUpdatedAt,
  onRefresh,
}: JobsPageProps) {
  const [statusFilter, setStatusFilter] = useState<JobFilter>('all');
  const [connectorFilter, setConnectorFilter] = useState<string>('all');

  const connectorNameById = useMemo(
    () => new Map(connectors.map((connector) => [connector.id, connector.display_name])),
    [connectors],
  );

  const filteredJobs = useMemo(() => {
    return jobs.filter((job) => {
      if (connectorFilter !== 'all' && job.connector_id !== connectorFilter) {
        return false;
      }
      if (statusFilter === 'active' && !isActiveJob(job)) {
        return false;
      }
      if (statusFilter === 'failed' && !isFailedJob(job)) {
        return false;
      }
      if (statusFilter === 'completed' && !isCompletedJob(job)) {
        return false;
      }
      return true;
    });
  }, [connectorFilter, jobs, statusFilter]);

  const activeJobs = jobs.filter(isActiveJob).length;
  const failedJobs = jobs.filter(isFailedJob).length;
  const completedJobs = jobs.filter(isCompletedJob).length;

  return (
    <section className="jobs-page">
      <section className="overview-grid" aria-label="Job statistics">
        <StatCard label="Total jobs" value={jobs.length.toString()} />
        <StatCard label="Active" value={activeJobs.toString()} />
        <StatCard label="Failed" value={failedJobs.toString()} />
        <StatCard label="Completed" value={completedJobs.toString()} />
      </section>

      <section className="card jobs-board">
        <header className="panel-header jobs-board__header">
          <div>
            <h3>Background jobs</h3>
            <p className="jobs-board__meta">
              {refreshing ? 'Polling…' : 'Auto-refresh every 5 seconds'}
              {lastUpdatedAt ? ` · Updated ${formatTimestamp(lastUpdatedAt)}` : ''}
            </p>
          </div>
          <div className="jobs-board__actions">
            <label className="jobs-filter">
              <span>Status</span>
              <select
                value={statusFilter}
                onChange={(event) => setStatusFilter(event.target.value as JobFilter)}
              >
                <option value="all">All</option>
                <option value="active">Active</option>
                <option value="failed">Failed</option>
                <option value="completed">Completed</option>
              </select>
            </label>
            <label className="jobs-filter">
              <span>Connector</span>
              <select
                value={connectorFilter}
                onChange={(event) => setConnectorFilter(event.target.value)}
              >
                <option value="all">All connectors</option>
                {connectors.map((connector) => (
                  <option key={connector.id} value={connector.id}>
                    {connector.display_name}
                  </option>
                ))}
              </select>
            </label>
            <button type="button" onClick={() => void onRefresh()} disabled={loading}>
              {loading ? 'Refreshing…' : 'Refresh now'}
            </button>
          </div>
        </header>

        {error ? (
          <div className="jobs-error" role="alert">
            {error}
          </div>
        ) : null}

        {loading && jobs.length === 0 ? (
          <div className="empty-state jobs-empty-state">
            <span>Loading jobs…</span>
          </div>
        ) : filteredJobs.length === 0 ? (
          <EmptyJobs />
        ) : (
          <div className="job-list jobs-page__list">
            {filteredJobs.map((job) => {
              const connectorName = connectorNameById.get(job.connector_id) ?? job.connector_id;
              return (
                <article key={job.id} className="job-card jobs-page__card">
                  <div className="job-card__info jobs-page__info">
                    <div className="jobs-page__headline">
                      <strong>{connectorName}</strong>
                      <div className="jobs-page__pills">
                        <span className={`pill pill--${job.status}`}>{job.status}</span>
                        {job.retry_count > 0 ? (
                          <span className="pill pill--pending">retry {job.retry_count}</span>
                        ) : null}
                      </div>
                    </div>
                    <p>{describeJob(job)}</p>
                    <dl className="jobs-page__details">
                      <div>
                        <dt>Queued</dt>
                        <dd>{formatTimestamp(job.created_at)}</dd>
                      </div>
                      <div>
                        <dt>Started</dt>
                        <dd>{formatTimestamp(job.started_at)}</dd>
                      </div>
                      <div>
                        <dt>Completed</dt>
                        <dd>{formatTimestamp(job.completed_at)}</dd>
                      </div>
                      <div>
                        <dt>Task</dt>
                        <dd>{job.worker_task_id ?? 'Pending assignment'}</dd>
                      </div>
                    </dl>
                    {job.error_message ? (
                      <p className="jobs-page__error">{job.error_message}</p>
                    ) : null}
                  </div>

                  <div className="job-card__status jobs-page__status">
                    <span className="job-card__progress-label">{getProgressLabel(job)}</span>
                    <JobProgressBar job={job} />
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </section>
    </section>
  );
}
