export const ACTIVE_JOBS_POLL_INTERVAL_MS = 5_000;
export const IDLE_JOBS_POLL_INTERVAL_MS = 20_000;

export type JobsPollable = {
  status: string;
};

export function isActiveJob(job: JobsPollable): boolean {
  return ['pending', 'queued', 'running', 'processing', 'retrying'].includes(job.status);
}

export function jobsPollIntervalMs(jobs: readonly JobsPollable[]): number {
  return jobs.some(isActiveJob) ? ACTIVE_JOBS_POLL_INTERVAL_MS : IDLE_JOBS_POLL_INTERVAL_MS;
}

export type JobsPollSchedulerOptions = {
  /** Immediate first load (non-silent). */
  load: (options: { silent: boolean }) => Promise<void>;
  /** Latest jobs snapshot for interval selection after each load. */
  getJobs: () => readonly JobsPollable[];
  /** Visibility gate; skipped polls still reschedule. */
  isVisible: () => boolean;
  setTimeoutFn?: typeof setTimeout;
  clearTimeoutFn?: typeof clearTimeout;
};

/**
 * Completion-based jobs poller: deps stay stable (no `jobs` in effect deps).
 * Each tick awaits the prior load, then schedules the next delay from current jobs.
 */
export function startJobsPollScheduler(options: JobsPollSchedulerOptions): () => void {
  const setTimeoutFn = options.setTimeoutFn ?? setTimeout;
  const clearTimeoutFn = options.clearTimeoutFn ?? clearTimeout;
  let disposed = false;
  let timer: ReturnType<typeof setTimeout> | undefined;

  const clearTimer = () => {
    if (timer !== undefined) {
      clearTimeoutFn(timer);
      timer = undefined;
    }
  };

  const scheduleNext = () => {
    clearTimer();
    if (disposed) {
      return;
    }
    const delay = jobsPollIntervalMs(options.getJobs());
    timer = setTimeoutFn(() => {
      void tick(true);
    }, delay);
  };

  const tick = async (silent: boolean) => {
    if (disposed) {
      return;
    }
    if (!options.isVisible()) {
      scheduleNext();
      return;
    }
    try {
      await options.load({ silent });
    } finally {
      if (!disposed) {
        scheduleNext();
      }
    }
  };

  void tick(false);

  return () => {
    disposed = true;
    clearTimer();
  };
}
