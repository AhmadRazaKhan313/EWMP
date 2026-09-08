import { describe, it, expect, vi } from "vitest";
import { OfflineOutbox, type SyncResult } from "../offlineQueue";

describe("OfflineOutbox", () => {
  it("enqueue immediately adds a pending item", () => {
    const outbox = new OfflineOutbox<{ action: string }>();
    outbox.enqueue("emp-1", { action: "check-in" });
    expect(outbox.size()).toBe(1);
    expect(outbox.getPending("emp-1")).toHaveLength(1);
  });

  it("syncAll removes an item on success", async () => {
    const outbox = new OfflineOutbox<{ action: string }>();
    outbox.enqueue("emp-1", { action: "check-in" });
    const syncFn = vi.fn(async (): Promise<SyncResult> => ({ success: true }));

    await outbox.syncAll(syncFn);

    expect(syncFn).toHaveBeenCalledTimes(1);
    expect(outbox.size()).toBe(0);
  });

  it("keeps a network-error item pending for retry (never marks it failed)", async () => {
    const outbox = new OfflineOutbox<{ action: string }>();
    outbox.enqueue("emp-1", { action: "check-in" });
    const syncFn = vi.fn(async (): Promise<SyncResult> => {
      throw new Error("network down");
    });

    await outbox.syncAll(syncFn);

    const pending = outbox.getPending("emp-1");
    expect(pending).toHaveLength(1);
    expect(pending[0]!.status).toBe("pending");
    expect(pending[0]!.attempts).toBe(1);
    expect(pending[0]!.lastError).toContain("network down");
  });

  it("retries a network error again on the next syncAll call", async () => {
    const outbox = new OfflineOutbox<{ action: string }>();
    outbox.enqueue("emp-1", { action: "check-in" });
    let callCount = 0;
    const syncFn = vi.fn(async (): Promise<SyncResult> => {
      callCount += 1;
      if (callCount < 3) throw new Error("still down");
      return { success: true };
    });

    await outbox.syncAll(syncFn);
    await outbox.syncAll(syncFn);
    await outbox.syncAll(syncFn);

    expect(syncFn).toHaveBeenCalledTimes(3);
    expect(outbox.size()).toBe(0);
  });

  it("NEVER retries a 4xx (client error) — moves it to failed instead", async () => {
    const outbox = new OfflineOutbox<{ action: string }>();
    outbox.enqueue("emp-1", { action: "check-in" });
    const syncFn = vi.fn(async (): Promise<SyncResult> => ({
      success: false,
      isClientError: true,
      error: "Validation failed",
    }));

    await outbox.syncAll(syncFn);
    await outbox.syncAll(syncFn); // a second call must NOT retry it

    expect(syncFn).toHaveBeenCalledTimes(1); // only ever attempted once
    expect(outbox.getPending("emp-1")).toHaveLength(0); // not "pending" anymore
  });

  it("preserves enqueue order within one queue key (check-in before check-out)", async () => {
    const outbox = new OfflineOutbox<{ action: string }>();
    outbox.enqueue("emp-1", { action: "check-in" });
    outbox.enqueue("emp-1", { action: "check-out" });

    const seenOrder: string[] = [];
    const syncFn = vi.fn(async (payload: { action: string }): Promise<SyncResult> => {
      seenOrder.push(payload.action);
      return { success: true };
    });

    await outbox.syncAll(syncFn);

    expect(seenOrder).toEqual(["check-in", "check-out"]);
  });

  it("isolates queues per key — one employee's failure doesn't block another's sync", async () => {
    const outbox = new OfflineOutbox<{ employee: string }>();
    outbox.enqueue("emp-1", { employee: "emp-1" });
    outbox.enqueue("emp-2", { employee: "emp-2" });

    const synced: string[] = [];
    const syncFn = vi.fn(async (payload: { employee: string }): Promise<SyncResult> => {
      if (payload.employee === "emp-1") throw new Error("emp-1 is offline");
      synced.push(payload.employee);
      return { success: true };
    });

    await outbox.syncAll(syncFn);

    expect(synced).toEqual(["emp-2"]);
    expect(outbox.getPending("emp-1")).toHaveLength(1); // still pending, will retry later
    expect(outbox.getPending("emp-2")).toHaveLength(0); // delivered
  });

  it("hasPendingWork reflects queued/syncing items for the syncing indicator", async () => {
    const outbox = new OfflineOutbox<{ action: string }>();
    expect(outbox.hasPendingWork()).toBe(false);
    outbox.enqueue("emp-1", { action: "check-in" });
    expect(outbox.hasPendingWork()).toBe(true);
    await outbox.syncAll(async () => ({ success: true }));
    expect(outbox.hasPendingWork()).toBe(false);
  });

  it("calls the persist callback after enqueue and after syncAll", async () => {
    const persist = vi.fn();
    const outbox = new OfflineOutbox<{ action: string }>({ persist });
    outbox.enqueue("emp-1", { action: "check-in" });
    expect(persist).toHaveBeenCalledTimes(1);

    await outbox.syncAll(async () => ({ success: true }));
    expect(persist).toHaveBeenCalledTimes(2);
  });

  it("restores from initialItems (surviving an app restart)", () => {
    const outbox = new OfflineOutbox<{ action: string }>({
      initialItems: [
        {
          id: "outbox_1",
          queueKey: "emp-1",
          payload: { action: "check-in" },
          status: "pending",
          attempts: 0,
          createdAt: Date.now(),
        },
      ],
    });
    expect(outbox.size()).toBe(1);
  });
});
