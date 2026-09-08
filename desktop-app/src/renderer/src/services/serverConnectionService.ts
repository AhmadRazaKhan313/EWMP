import axios from "axios";

export interface HealthCheckResult {
  ok: boolean;
  message: string;
}

/** Hits GET {base}/health directly (plain axios, not the shared apiClient
 * — no token/tenant headers apply here, and we don't want this call
 * going through the 401-refresh interceptor). Used by the server setup
 * screen to validate a URL before saving it. */
export async function checkServerHealth(rawBaseUrl: string): Promise<HealthCheckResult> {
  const base = rawBaseUrl.trim().replace(/\/+$/, "");
  if (!base) {
    return { ok: false, message: "Enter a server address" };
  }
  const url = /^https?:\/\//i.test(base) ? base : `http://${base}`;

  try {
    const { data } = await axios.get<{ status: string }>(`${url}/health`, { timeout: 5000 });
    if (data.status === "healthy") {
      return { ok: true, message: "Connected" };
    }
    return { ok: false, message: `Server responded but reported status: ${data.status}` };
  } catch (err) {
    if (axios.isAxiosError(err)) {
      if (err.code === "ECONNABORTED") {
        return { ok: false, message: "Connection timed out — check the address and that the server is running" };
      }
      if (err.response) {
        return { ok: false, message: `Server responded with an unexpected error (${err.response.status})` };
      }
      return { ok: false, message: "Could not reach that address — check it's correct and the server is running" };
    }
    return { ok: false, message: "Could not reach that address" };
  }
}

/** Normalizes user input ("192.168.1.50:8000", "http://x:8000/") into the
 * clean base URL form the app stores (e.g. "http://192.168.1.50:8000"). */
export function normalizeServerUrl(input: string): string {
  const trimmed = input.trim().replace(/\/+$/, "");
  return /^https?:\/\//i.test(trimmed) ? trimmed : `http://${trimmed}`;
}
