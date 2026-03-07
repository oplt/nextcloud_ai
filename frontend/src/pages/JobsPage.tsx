import { JobStatusList } from '../components/JobStatusList';
import type { Connector, SyncJob } from '../types/api';

type JobsPageProps = {
  jobs: SyncJob[];
  connectors: Connector[];
};

export function JobsPage({ jobs, connectors }: JobsPageProps) {
  return <JobStatusList jobs={jobs} connectors={connectors} />;
}
