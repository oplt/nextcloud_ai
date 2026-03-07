import type { Connector, SyncJob } from '../types/api';

type JobStatusListProps = {
  jobs: SyncJob[];
  connectors: Connector[];
};

export function JobStatusList({ jobs, connectors }: JobStatusListProps) {
  const connectorNameById = new Map(connectors.map((connector) => [connector.id, connector.display_name]));

  return (
    <div className="card table-card">
      <header className="panel-header">
        <h3>Background Jobs</h3>
        <span>{jobs.length}</span>
      </header>
      <div className="job-list">
        {jobs.length === 0 ? <p className="empty-state">No jobs queued yet.</p> : null}
        {jobs.map((job) => (
          <article key={job.id} className="job-card">
            <div>
              <strong>{connectorNameById.get(job.connector_id) ?? job.connector_id}</strong>
              <p>{job.job_type}</p>
            </div>
            <div>
              <span className={`pill pill--${job.status}`}>{job.status}</span>
              <p>
                {job.progress_completed ?? 0}/{job.progress_total ?? 0}
              </p>
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}
