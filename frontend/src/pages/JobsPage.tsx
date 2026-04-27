import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import ScheduleOutlinedIcon from '@mui/icons-material/ScheduleOutlined';
import Alert from '@mui/material/Alert';

import { AppButton } from '../components/ui/AppButton';
import { AppCard } from '../components/ui/AppCard';
import { EmptyState } from '../components/ui/EmptyState';
import { AppSelectField } from '../components/ui/AppSelectField';
import { StatusBadge } from '../components/ui/StatusBadge';
import { statusToneFromValue } from '../components/ui/statusTone';
import { TooltipInfo } from '../components/ui/TooltipInfo';
import type { Connector, SyncJob } from '../types/api';

type JobsPageProps = {
  jobs: SyncJob[];
  connectors: Connector[];
  loading: boolean;
  refreshing: boolean;
  error: string | null;
  lastUpdatedAt: string | null;
  onRefresh: () => Promise<void>;
  onRetry: (jobId: string) => Promise<void>;
};

type JobFilter = 'all' | 'active' | 'failed' | 'completed';

function isActiveJob(job: SyncJob): boolean {
  return ['pending', 'queued', 'running', 'processing', 'retrying'].includes(job.status);
}

function isFailedJob(job: SyncJob): boolean {
  return ['failed', 'error', 'dead_lettered'].includes(job.status);
}

function isCompletedJob(job: SyncJob): boolean {
  return ['done', 'completed', 'succeeded'].includes(job.status);
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

function extractFailureRows(job: SyncJob): Array<Record<string, unknown>> {
  const failures = job.result_json?.failures;
  return Array.isArray(failures) ? (failures as Array<Record<string, unknown>>) : [];
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
    <EmptyState
      title="No jobs for this filter"
      description="Try changing status or connector filters."
      icon={<ScheduleOutlinedIcon fontSize="medium" />}
      className="jobs-empty-state"
    />
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <AppCard className="card stat-card">
      <span className="stat-card__label">{label}</span>
      <strong className="stat-card__value">{value}</strong>
    </AppCard>
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
  onRetry,
}: JobsPageProps) {
  const [searchParams] = useSearchParams();
  const [statusFilter, setStatusFilter] = useState<JobFilter>('all');
  const [connectorFilter, setConnectorFilter] = useState<string>('all');

  useEffect(() => {
    const raw = (searchParams.get('status') ?? '').toLowerCase();
    if (raw === 'failed' || raw === 'active' || raw === 'completed' || raw === 'all') {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setStatusFilter(raw as JobFilter);
    }
  }, [searchParams]);

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

      <AppCard component="section" className="card jobs-board">
        <header className="panel-header jobs-board__header">
          <div>
            <h3>
              Background jobs
              <TooltipInfo title="Jobs are auto-polled and cached to reduce duplicate network requests." />
            </h3>
            <p className="jobs-board__meta">
              {refreshing ? 'Polling…' : 'Auto-refresh every 5 seconds'}
              {lastUpdatedAt ? ` · Updated ${formatTimestamp(lastUpdatedAt)}` : ''}
            </p>
          </div>
          <div className="jobs-board__actions">
            <AppSelectField
              label="Status"
              value={statusFilter}
              onChange={(event) => setStatusFilter(event.target.value as JobFilter)}
              options={[
                { label: 'All', value: 'all' },
                { label: 'Active', value: 'active' },
                { label: 'Failed', value: 'failed' },
                { label: 'Completed', value: 'completed' },
              ]}
            />
            <AppSelectField
              label="Connector"
              value={connectorFilter}
              onChange={(event) => setConnectorFilter(event.target.value)}
              options={[
                { label: 'All connectors', value: 'all' },
                ...connectors.map((connector) => ({ label: connector.display_name, value: connector.id })),
              ]}
            />
            <AppButton type="button" variant="outlined" onClick={() => void onRefresh()} disabled={loading}>
              {loading ? 'Refreshing…' : 'Refresh now'}
            </AppButton>
          </div>
        </header>

        {error ? (
          <Alert severity="error" className="jobs-error">
            {error}
          </Alert>
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
              const connectorName =
                job.connector?.display_name ??
                connectorNameById.get(job.connector_id) ??
                job.connector_id;
              const failures = extractFailureRows(job);
              return (
                <article key={job.id} className="job-card jobs-page__card">
                  <div className="job-card__info jobs-page__info">
                    <div className="jobs-page__headline">
                      <strong>{connectorName}</strong>
                      <div className="jobs-page__pills">
                        <StatusBadge label={job.status} tone={statusToneFromValue(job.status)} />
                        {job.retry_count > 0 ? (
                          <StatusBadge label={`retry ${job.retry_count}`} tone="warning" />
                        ) : null}
                      </div>
                    </div>
                    <p>{describeJob(job)}</p>
                    <dl className="jobs-page__details">
                      <div>
                        <dt>Queued -- {formatTimestamp(job.created_at)}</dt>
                      </div>
                      <div>
                        <dt>Started -- {formatTimestamp(job.started_at)}</dt>
                      </div>
                      <div>
                        <dt>Completed -- {formatTimestamp(job.completed_at)}</dt>
                      </div>
                      <div>
                        <dt>Task: {job.worker_task_id ?? 'Pending assignment'}</dt>
                      </div>
                    </dl>
                    {job.error_message ? (
                      <p className="jobs-page__error">{job.error_message}</p>
                    ) : null}
                    {failures.length > 0 ? (
                      <div className="jobs-page__failures">
                        <strong>Failed documents</strong>
                        <ul>
                          {failures.slice(0, 3).map((failure, index) => (
                            <li key={`${job.id}-failure-${index}`}>
                              <span>{String(failure.file_path ?? failure.external_id ?? 'unknown document')}</span>
                              <small>{String(failure.error ?? 'Unknown error')}</small>
                            </li>
                          ))}
                        </ul>
                      </div>
                    ) : null}
                  </div>

                  <div className="job-card__status jobs-page__status">
                    <span className="job-card__progress-label">{getProgressLabel(job)}</span>
                    <JobProgressBar job={job} />
                    {isFailedJob(job) ? (
                      <AppButton type="button" variant="outlined" onClick={() => void onRetry(job.id)}>
                        Retry job
                      </AppButton>
                    ) : null}
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </AppCard>
    </section>
  );
}
