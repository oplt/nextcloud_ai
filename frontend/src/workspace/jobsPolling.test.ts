import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  ACTIVE_JOBS_POLL_INTERVAL_MS,
  IDLE_JOBS_POLL_INTERVAL_MS,
  jobsPollIntervalMs,
  startJobsPollScheduler,
} from './jobsPolling';

describe('jobsPollIntervalMs', () => {
  it('uses active interval when any job is running', () => {
    expect(jobsPollIntervalMs([{ status: 'running' }])).toBe(ACTIVE_JOBS_POLL_INTERVAL_MS);
  });

  it('uses idle interval when no active jobs', () => {
    expect(jobsPollIntervalMs([{ status: 'succeeded' }])).toBe(IDLE_JOBS_POLL_INTERVAL_MS);
  });
});

describe('startJobsPollScheduler', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('does not storm: one load per interval; jobs snapshot does not restart poller', async () => {
    const load = vi.fn(async () => undefined);
    let jobs: Array<{ status: string }> = [{ status: 'succeeded' }];

    const stop = startJobsPollScheduler({
      load,
      getJobs: () => jobs,
      isVisible: () => true,
      setTimeoutFn: setTimeout,
      clearTimeoutFn: clearTimeout,
    });

    await Promise.resolve();
    expect(load).toHaveBeenCalledTimes(1);
    expect(load).toHaveBeenLastCalledWith({ silent: false });

    // Mutating jobs must not by itself trigger extra loads (stable scheduler).
    jobs = [{ status: 'running' }];
    await Promise.resolve();
    expect(load).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(IDLE_JOBS_POLL_INTERVAL_MS);
    expect(load).toHaveBeenCalledTimes(2);
    expect(load).toHaveBeenLastCalledWith({ silent: true });

    // After a load while active, next delay should be the active interval.
    await vi.advanceTimersByTimeAsync(ACTIVE_JOBS_POLL_INTERVAL_MS);
    expect(load).toHaveBeenCalledTimes(3);

    stop();
    await vi.advanceTimersByTimeAsync(ACTIVE_JOBS_POLL_INTERVAL_MS * 5);
    expect(load).toHaveBeenCalledTimes(3);
  });

  it('skips load while hidden but still reschedules', async () => {
    const load = vi.fn(async () => undefined);
    let visible = true;

    const stop = startJobsPollScheduler({
      load,
      getJobs: () => [{ status: 'succeeded' }],
      isVisible: () => visible,
      setTimeoutFn: setTimeout,
      clearTimeoutFn: clearTimeout,
    });

    await Promise.resolve();
    expect(load).toHaveBeenCalledTimes(1);

    visible = false;
    await vi.advanceTimersByTimeAsync(IDLE_JOBS_POLL_INTERVAL_MS);
    expect(load).toHaveBeenCalledTimes(1);

    visible = true;
    await vi.advanceTimersByTimeAsync(IDLE_JOBS_POLL_INTERVAL_MS);
    expect(load).toHaveBeenCalledTimes(2);

    stop();
  });
});
