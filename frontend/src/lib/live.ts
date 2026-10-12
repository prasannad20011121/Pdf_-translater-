/**
 * Pause before reconnecting live updates after the connection dropped (the app was
 * restarted, the laptop slept): 2, 4, 8, 16, then every 30 seconds. Live updates never
 * stop for good while the job runs.
 */
export function reconnectDelay(failures: number): number {
  return Math.min(30_000, 1000 * 2 ** Math.min(Math.max(failures, 1), 5));
}
