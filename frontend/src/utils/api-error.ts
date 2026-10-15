/**
 * One place that turns any API error into a plain string that is always safe to
 * render or pass to toast. The backend can answer with:
 *   - detail: "text"
 *   - detail: [{ field, message, type }]   (our 422 handler)
 *   - detail: [{ loc, msg }]               (FastAPI default)
 *   - message: "text"
 * Putting an object into a toast/JSX crashes React ("Objects are not valid as a
 * React child"), so every call site should go through this.
 */
type Item = { field?: unknown; message?: unknown; msg?: unknown; loc?: unknown };

function itemText(item: unknown): string | null {
  if (typeof item === "string") return item;
  if (!item || typeof item !== "object") return null;
  const i = item as Item;
  const text = typeof i.message === "string" ? i.message : typeof i.msg === "string" ? i.msg : null;
  if (!text) return null;
  const where = typeof i.field === "string" ? i.field : Array.isArray(i.loc) ? String(i.loc[i.loc.length - 1] ?? "") : "";
  const label = where.split("→").pop()?.trim();
  return label && label !== "body" ? `${label}: ${text}` : text;
}

export function apiErrorText(error: unknown, fallback: string): string {
  const data = (error as { response?: { data?: { detail?: unknown; message?: unknown } } })?.response?.data;
  const detail = data?.detail;
  if (typeof detail === "string" && detail) return detail;
  if (Array.isArray(detail)) {
    const parts = detail.map(itemText).filter((t): t is string => !!t);
    if (parts.length) return parts.slice(0, 3).join(" · ");
  } else {
    const one = itemText(detail);
    if (one) return one;
  }
  if (typeof data?.message === "string" && data.message) return data.message;
  return fallback;
}
