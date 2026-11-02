/**
 * The two pages a candidate / new hire sees without logging in. They must never
 * let a half-filled form through and must say plainly when a link can't be used.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const m = vi.hoisted(() => ({
  getOffer: vi.fn(), accept: vi.fn(), decline: vi.fn(),
  getPre: vi.fn(), savePre: vi.fn(), upload: vi.fn(),
}));

vi.mock("next/navigation", () => ({ useParams: () => ({ token: "tok" }) }));
vi.mock("@/services/onboarding.service", () => ({
  publicOfferApi: { get: m.getOffer, accept: m.accept, decline: m.decline },
  preboardingApi: { get: m.getPre, save: m.savePre, upload: m.upload },
  apiErrorMessage: (_e: unknown, fallback: string) => fallback,
}));

import PublicOfferPage from "../offer/[token]/page";
import PreboardingPage from "../preboarding/[token]/page";

const wrap = (ui: React.ReactElement) =>
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{ui}</QueryClientProvider>);

const offer = (over = {}) => ({
  company_name: "Acme", candidate_name: "Sara Khan", job_title: "Engineer", joining_date: "2026-11-01",
  salary: 100000, currency: "PKR", pay_items: [], body: null, status: "sent", expires_at: null, can_respond: true, ...over,
});

beforeEach(() => vi.clearAllMocks());

describe("public offer page", () => {
  it("keeps Accept disabled until a name is typed and the box is ticked", async () => {
    m.getOffer.mockResolvedValue(offer());
    wrap(<PublicOfferPage />);
    const btn = await screen.findByRole("button", { name: "Accept offer" });
    expect(btn).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Full name"), "Sara Khan");
    expect(btn).toBeDisabled();
    await userEvent.click(screen.getByRole("checkbox"));
    expect(btn).toBeEnabled();
    m.accept.mockResolvedValue(offer({ status: "accepted", can_respond: false }));
    await userEvent.click(btn);
    await waitFor(() => expect(m.accept).toHaveBeenCalledWith("tok", "Sara Khan", true));
  });

  it("shows a message instead of the form when the offer can't be answered", async () => {
    m.getOffer.mockResolvedValue(offer({ status: "expired", can_respond: false }));
    wrap(<PublicOfferPage />);
    expect(await screen.findByText(/has expired/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Accept offer" })).toBeNull();
  });

  it("says the link is invalid when the server rejects it", async () => {
    m.getOffer.mockRejectedValue(new Error("404"));
    wrap(<PublicOfferPage />);
    expect(await screen.findByText(/link is not valid/i)).toBeInTheDocument();
  });
});

describe("pre-boarding page", () => {
  const view = (over = {}) => ({
    company_name: "Acme", first_name: "Sara", joining_date: "2026-11-01", submitted: false, policy_acknowledged: false,
    form: {}, documents: [], required_fields: ["personal_phone", "address", "national_id"], ...over,
  });

  it("only allows Submit once required fields are filled and policies acknowledged", async () => {
    m.getPre.mockResolvedValue(view());
    m.savePre.mockResolvedValue(view({ submitted: true }));
    wrap(<PreboardingPage />);
    const submit = await screen.findByRole("button", { name: "Submit" });
    expect(submit).toBeDisabled();
    expect(screen.getByText(/To submit, please fill in/)).toBeInTheDocument();
    const inputs = screen.getAllByRole("textbox");
    const byLabel = (re: RegExp) => screen.getByLabelText(re);
    await userEvent.type(byLabel(/Mobile number/), "03001234567");
    await userEvent.type(byLabel(/Current address/), "House 1");
    await userEvent.type(byLabel(/National ID/), "31201-1234567-1");
    expect(inputs.length).toBeGreaterThan(3);
    expect(submit).toBeDisabled(); // policy not yet acknowledged
    await userEvent.click(screen.getByRole("checkbox"));
    expect(submit).toBeEnabled();
    await userEvent.click(submit);
    await waitFor(() => expect(m.savePre).toHaveBeenCalled());
    const body = m.savePre.mock.calls[0]![1];
    expect(body.submit).toBe(true);
    expect(body.acknowledge_policy).toBe(true);
    expect(body.form.personal_phone).toBe("03001234567");
  });

  it("Save for later works without the required fields", async () => {
    m.getPre.mockResolvedValue(view());
    m.savePre.mockResolvedValue(view());
    wrap(<PreboardingPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Save for later" }));
    await waitFor(() => expect(m.savePre).toHaveBeenCalled());
    expect(m.savePre.mock.calls[0]![1].submit).toBe(false);
  });
});
