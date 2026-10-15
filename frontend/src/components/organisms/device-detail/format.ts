export function fmtGb(gb: number | null | undefined) {
  if (gb === null || gb === undefined) return "—";
  return `${gb.toFixed(1)} GB`;
}

export function fmtDate(iso: string | null | undefined) {
  if (!iso) return "Never";
  const diff = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

export const TABS = [
  { id: "overview", label: "Overview", title: "Device overview", subtitle: "Status, health, hardware and who this device is assigned to." },
  { id: "metrics", label: "Metrics", title: "Performance metrics", subtitle: "CPU, memory and disk usage reported by the device." },
  { id: "screen", label: "Screen", title: "Screen captures", subtitle: "Still images taken about once a minute while the device is connected." },
  { id: "alerts", label: "Alerts", title: "Flagged activity", subtitle: "Matches against the organization's watch-list only." },
  { id: "allowed", label: "Allowed apps", title: "Allowed apps", subtitle: "Stop alerts for specific apps or sites on this device only." },
  { id: "processes", label: "Processes", title: "Running processes", subtitle: "Latest snapshot, top by memory usage." },
] as const;

export type TabId = (typeof TABS)[number]["id"];
