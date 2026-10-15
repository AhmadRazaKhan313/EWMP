/**
 * Desktop App <-> Widget attendance sync, on the same machine.
 *
 * The main window and the widget are two separate renderer processes, each with
 * its own copy of the timer store. When one of them changes the attendance
 * state on the server (check in/out, break on/off) it tells the main process,
 * which tells every OTHER window to re-read the server right away -- no waiting
 * for the next poll. The state itself is never copied between windows: they
 * only get a "something changed" nudge and fetch the truth from the backend.
 * (Another device or the website is picked up by the periodic re-read.)
 */

export interface BroadcastTarget {
  id: number;
  isDestroyed(): boolean;
  send(channel: string): void;
}

/** Sends `channel` to every window except the one that raised the change. */
export function relayToOtherWindows(targets: BroadcastTarget[], senderId: number, channel: string): number {
  let sent = 0;
  for (const target of targets) {
    if (target.id === senderId || target.isDestroyed()) continue;
    target.send(channel);
    sent += 1;
  }
  return sent;
}
