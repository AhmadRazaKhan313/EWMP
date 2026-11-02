// Uploaded pictures (profile photos) come back from the API as a path like
// "/api/v1/auth/avatar/<id>?v=…". In the browser a bare path would be fetched
// from the website's own address (the Next.js server), not from the API — so
// point it at the API's origin. Full URLs (S3, data:, blob:) are left alone.

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

export function resolveMediaUrl(url?: string | null): string | null {
  if (!url) return null;
  if (/^(https?:|data:|blob:)/i.test(url)) return url;
  if (!url.startsWith("/")) return url;
  try {
    return new URL(API_BASE).origin + url;
  } catch {
    return url;
  }
}
