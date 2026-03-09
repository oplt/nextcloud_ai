import type { Connector, SyncJob } from '../types/api';

type JobStatusListProps = {
  jobs: SyncJob[];
  connectors: Connector[];
};

function JobProgressBar({ job }: { job: SyncJob }) {
  const total     = job.progress_total     ?? 0;
  const completed = job.progress_completed ?? 0;
  const pct       = total > 0 ? Math.min(100, Math.round((completed / total) * 100)) : 0;

  const fillClass =
    job.status === 'done'                              ? 'job-progress__fill--done'
    : job.status === 'failed' || job.status === 'error' ? 'job-progress__fill--error'
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
    <div className="empty-state">
      <div className="empty-state-icon" aria-hidden="true">
        <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5">
          <circle cx="10" cy="10" r="8" strokeLinecap="round" />
          <path d="M10 6v4l2.5 2.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </div>
      <span>No jobs queued yet.</span>
    </div>
  );
}

export function JobStatusList({ jobs, connectors }: JobStatusListProps) {
  const nameById = new Map(connectors.map((c) => [c.id, c.display_name]));

  return (
    <div className="card table-card">
      <header className="panel-header">
        <h3>Background Jobs</h3>
        {jobs.length > 0 ? <span>{jobs.length}</span> : null}
      </header>

      {jobs.length === 0 ? (
        <EmptyJobs />
      ) : (
        <div className="job-list">
          {jobs.map((job) => {
            const completed = job.progress_completed ?? 0;
            const total     = job.progress_total     ?? 0;
            return (
              <article key={job.id} className="job-card">
                <div className="job-card__info">
                  <strong>{nameById.get(job.connector_id) ?? job.connector_id}</strong>
                  <p>{job.job_type}</p>
                </div>
                <div className="job-card__status">
                  <span className={`pill pill--${job.status}`}>{job.status}</span>
                  <JobProgressBar job={job} />
                  <span className="job-card__progress-label">{completed}/{total}</span>
                </div>
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
}
