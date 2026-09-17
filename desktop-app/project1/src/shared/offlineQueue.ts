/**
 * Generic offline outbox: every employee action queues here BEFORE going
 * over the network (per rules.md §6, referenced in the roadmap). This
 * class owns the core behavior — order preservation, retry-on-network-
 * error, never-retry-on-4xx, per-queue-key isolation — independent of how
 * items are actually persisted or synced, so it's fully unit-testable
 * without Electron, IPC, or a real network.
 *
 * Later phases (Home/Timer, Break management) wire:
 *   - a `persist` callback (e.g. writing to disk via IPC) so queued items
 *     survive an app restart before they've synced
 *   - a real `syncFn` that actually calls the API
 *
 * For now (Phase 1), this is infrastructure only — nothing enqueues to it
 * yet.
 */

export type OutboxItemStatus = "pending" | "syncing" | "failed";

export interface OutboxItem<T> {
  id: string;
  queueKey: string; // e.g. an employee id, so queues are isolated per-employee
  payload: T;
  status: OutboxItemStatus;
  attempts: number;
  createdAt: number;
  lastError?: string;
}

export interface SyncResult {
  /** True if the item should be considered delivered and removed. */
  success: boolean;
  /**
   * True if this was a genuine 4xx (bad request/validation/etc) — these
   * are NEVER retried, since retrying an inherently-invalid request just
   * wastes cycles and can duplicate side effects. False (or omitted) means
   * a network/5xx failure, which IS retried.
   */
  isClientError?: boolean;
  error?: string;
}

export type SyncFn<T> = (payload: T) => Promise<SyncResult>;
export type PersistFn<T> = (items: OutboxItem<T>[]) => void | Promise<void>;

let idCounter = 0;
function nextId(): string {
  idCounter += 1;
  return `outbox_${Date.now()}_${idCounter}`;
}

export class OfflineOutbox<T> {
  private items: OutboxItem<T>[] = [];
  private readonly persist?: PersistFn<T>;

  constructor(options?: { persist?: PersistFn<T>; initialItems?: OutboxItem<T>[] }) {
    this.persist = options?.persist;
    if (options?.initialItems) {
      this.items = [...options.initialItems];
    }
  }

  /** Queue an action. Always succeeds immediately (in-memory) — the actual
   * network call happens later via `syncAll`. */
  enqueue(queueKey: string, payload: T): OutboxItem<T> {
    const item: OutboxItem<T> = {
      id: nextId(),
      queueKey,
      payload,
      status: "pending",
      attempts: 0,
      createdAt: Date.now(),
    };
    this.items.push(item);
    void this.persist?.(this.items);
    return item;
  }

  getPending(queueKey?: string): OutboxItem<T>[] {
    const pending = this.items.filter((i) => i.status === "pending");
    return queueKey ? pending.filter((i) => i.queueKey === queueKey) : pending;
  }

  size(queueKey?: string): number {
    return this.getPending(queueKey).length;
  }

  /**
   * Attempt to sync every pending item, in enqueue order, per queueKey
   * (never syncs two items for the same key out of order — e.g. a
   * check-in must sync before that same employee's check-out does).
   * Successful items are removed; failed-with-4xx items are moved to
   * "failed" and never retried; failed-with-network-error items stay
   * "pending" for the next call.
   */
  async syncAll(syncFn: SyncFn<T>): Promise<void> {
    const byQueue = new Map<string, OutboxItem<T>[]>();
    for (const item of this.items) {
      if (item.status === "failed") continue;
      const bucket = byQueue.get(item.queueKey) ?? [];
      bucket.push(item);
      byQueue.set(item.queueKey, bucket);
    }

    for (const bucket of byQueue.values()) {
      // Sequential, in order — never parallel within one queue key.
      for (const item of bucket) {
        item.status = "syncing";
        try {
          const result = await syncFn(item.payload);
          if (result.success) {
            this.items = this.items.filter((i) => i.id !== item.id);
          } else if (result.isClientError) {
            item.status = "failed";
            item.lastError = result.error;
          } else {
            item.status = "pending";
            item.attempts += 1;
            item.lastError = result.error;
          }
        } catch (err) {
          // Threw (network error) — never a 4xx, always retryable.
          item.status = "pending";
          item.attempts += 1;
          item.lastError = err instanceof Error ? err.message : String(err);
        }
      }
    }

    void this.persist?.(this.items);
  }

  /** For the "syncing…" indicator: true if anything is queued or mid-sync. */
  hasPendingWork(queueKey?: string): boolean {
    return this.size(queueKey) > 0;
  }
}
