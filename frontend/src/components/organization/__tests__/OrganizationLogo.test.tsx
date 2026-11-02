/**
 * O-01: the organization logo. The sidebar shows it (falling back to the EWMP
 * mark when there is none), Settings has an upload card that checks the file
 * first and only offers changes to settings.manage.
 *
 * Run:  cd frontend && npm test -- OrganizationLogo
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

let perms: string[] = [];
let orgId: string | undefined = "org-1";
vi.mock("@/store/auth.store", () => {
  const useAuthStore = (sel?: (s: unknown) => unknown) => {
    const state = { user: orgId ? { organization_id: orgId } : { organization_id: undefined }, hasPermission: (p: string) => perms.includes(p) };
    return sel ? sel(state) : state;
  };
  return { useAuthStore };
});
vi.mock("@/services/api-client", () => ({ default: { get: vi.fn(), post: vi.fn(), delete: vi.fn() } }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import apiClient from "@/services/api-client";
import { toast } from "sonner";
import { LOGO_CHANGED_EVENT, logoProblem } from "@/services/organization.service";
import { BrandMark } from "../BrandMark";
import { OrganizationLogoCard } from "../OrganizationLogoCard";

const api = apiClient as unknown as Record<"get" | "post" | "delete", ReturnType<typeof vi.fn>>;
const org = (logo_url: string | null) => ({
  id: "org-1", name: "Acme", slug: "acme", email: "a@a.com", phone: null, website: null, country: null,
  timezone: "UTC", currency: "PKR", work_days: ["mon"], standard_work_hours_per_day: 8, logo_url,
});

function wrap(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

beforeEach(() => {
  vi.clearAllMocks();
  perms = [];
  orgId = "org-1";
});

describe("logoProblem", () => {
  it("accepts the four image types and refuses everything else or anything over 2 MB", () => {
    for (const type of ["image/png", "image/jpeg", "image/webp", "image/svg+xml"]) {
      expect(logoProblem({ type, size: 1000 })).toBeNull();
    }
    expect(logoProblem({ type: "application/pdf", size: 1000 })).toMatch(/PNG, JPEG, WebP or SVG/);
    expect(logoProblem({ type: "image/gif", size: 1000 })).not.toBeNull();
    expect(logoProblem({ type: "image/png", size: 2 * 1024 * 1024 + 1 })).toMatch(/2 MB/);
  });
});

describe("BrandMark (sidebar)", () => {
  it("shows the EWMP mark until the logo has loaded, then the logo instead", () => {
    render(<BrandMark />);
    expect(screen.getByText("EWMP")).toBeInTheDocument();
    const img = screen.getByTestId("org-logo") as HTMLImageElement;
    expect(img.src).toContain("/api/v1/organization/logo/org-1");
    expect(img.className).toContain("hidden");
    fireEvent.load(img);
    expect(screen.queryByText("EWMP")).toBeNull();
    expect(screen.getByTestId("org-logo").className).not.toContain("hidden");
  });

  it("keeps the EWMP mark when the organization has no logo (404)", () => {
    render(<BrandMark />);
    fireEvent.error(screen.getByTestId("org-logo"));
    expect(screen.getByText("EWMP")).toBeInTheDocument();
  });

  it("looks again after a logo is uploaded or removed in Settings", () => {
    render(<BrandMark />);
    fireEvent.error(screen.getByTestId("org-logo"));
    act(() => { window.dispatchEvent(new Event(LOGO_CHANGED_EVENT)); });
    expect((screen.getByTestId("org-logo") as HTMLImageElement).src).toContain("?v=1");
  });

  it("needs no QueryClientProvider and shows only the mark with no organization id", () => {
    orgId = undefined;
    render(<BrandMark />);
    expect(screen.getByText("EWMP")).toBeInTheDocument();
    expect(screen.queryByTestId("org-logo")).toBeNull();
  });
});

describe("OrganizationLogoCard (Settings -> General)", () => {
  it("shows a read-only card, with no buttons, to someone without settings.manage", async () => {
    api.get.mockResolvedValue({ data: org("/api/v1/organization/logo/org-1?v=1") });
    wrap(<OrganizationLogoCard />);
    await screen.findByAltText("Organization logo");
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByText(/needs the/i)).toBeInTheDocument();
  });

  it("uploads a valid file and refuses a bad one without calling the server", async () => {
    perms = ["settings.manage"];
    api.get.mockResolvedValue({ data: org(null) });
    api.post.mockResolvedValue({ data: org("/api/v1/organization/logo/org-1?v=2") });
    wrap(<OrganizationLogoCard />);
    const input = await screen.findByLabelText("Upload organization logo");

    await userEvent.upload(input, new File(["%PDF"], "doc.pdf", { type: "application/pdf" }), { applyAccept: false });
    expect(toast.error).toHaveBeenCalledWith(expect.stringMatching(/PNG, JPEG, WebP or SVG/));
    expect(api.post).not.toHaveBeenCalled();

    await userEvent.upload(input, new File(["x"], "logo.png", { type: "image/png" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/organization/logo", expect.any(FormData), expect.anything()));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Logo updated"));
  });

  it("can remove an existing logo", async () => {
    perms = ["settings.manage"];
    api.get.mockResolvedValue({ data: org("/api/v1/organization/logo/org-1?v=1") });
    api.delete.mockResolvedValue({ data: org(null) });
    wrap(<OrganizationLogoCard />);
    await userEvent.click(await screen.findByRole("button", { name: /remove/i }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith("/organization/logo"));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Logo removed"));
  });

  it("shows the server's message when the upload is refused", async () => {
    perms = ["settings.manage"];
    api.get.mockResolvedValue({ data: org(null) });
    api.post.mockRejectedValue({ response: { data: { message: "This SVG is not allowed (it contains <script>)" } } });
    wrap(<OrganizationLogoCard />);
    await userEvent.upload(await screen.findByLabelText("Upload organization logo"), new File(["<svg/>"], "l.svg", { type: "image/svg+xml" }));
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith(expect.stringContaining("not allowed")));
  });
});
