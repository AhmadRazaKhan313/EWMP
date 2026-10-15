/**
 * The "Assign employees" dialog on the Shifts page.
 *
 * The list saved is the WHOLE roster of the shift (PUT /shifts/{id}/employees):
 * ticked = on the shift, unticked = off it. The easy way to get that wrong is a
 * search that quietly drops people from the selection, so that is pinned here.
 *
 * Run:  cd frontend && npm test -- AssignEmployeesDialog
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const { getMock, putMock } = vi.hoisted(() => ({ getMock: vi.fn(), putMock: vi.fn() }));
vi.mock("@/services/api-client", () => ({ default: { get: getMock, put: putMock } }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { AssignEmployeesDialog } from "../AssignEmployeesDialog";

const row = (id: string, name: string, shiftId: string | null = null, shiftName: string | null = null) => ({
  id, employee_code: `E-${id}`, name, department_name: null, current_shift_id: shiftId, current_shift_name: shiftName,
});

const ROSTER = {
  shift: { id: "day", name: "Day", code: "DAY" },
  assigned: [row("a", "Ann Assigned", "day", "Day")],
  others: [row("b", "Ben Free"), row("c", "Cat Nights", "night", "Night")],
};

function renderDialog(onClose = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <AssignEmployeesDialog shift={{ id: "day", name: "Day" }} onClose={onClose} />
    </QueryClientProvider>,
  );
  return onClose;
}

const box = (name: string) => screen.getByText(name).closest("label")!.querySelector("input")!;

describe("AssignEmployeesDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getMock.mockImplementation(async (_url: string, cfg?: { params?: { search?: string } }) => {
      const s = cfg?.params?.search?.toLowerCase();
      if (!s) return { data: ROSTER };
      const keep = (e: ReturnType<typeof row>) => e.name.toLowerCase().includes(s);
      return { data: { ...ROSTER, assigned: ROSTER.assigned.filter(keep), others: ROSTER.others.filter(keep) } };
    });
    putMock.mockResolvedValue({ data: { assigned: 2, cleared: 0 } });
  });

  it("starts with the shift's current employees ticked and shows who would be moved", async () => {
    renderDialog();
    await screen.findByText("Ann Assigned");
    await waitFor(() => expect(box("Ann Assigned")).toBeChecked());
    expect(box("Ben Free")).not.toBeChecked();
    expect(screen.getByText("now on Night")).toBeInTheDocument();
    expect(screen.getByText("1 selected")).toBeInTheDocument();
  });

  it("saves the complete roster: current + newly ticked, minus unticked", async () => {
    const onClose = renderDialog();
    await waitFor(() => expect(box("Ann Assigned")).toBeChecked());
    await userEvent.click(box("Ben Free"));        // add Ben
    await userEvent.click(box("Ann Assigned"));    // remove Ann
    await userEvent.click(box("Cat Nights"));      // move Cat here
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(putMock).toHaveBeenCalledTimes(1));
    const [url, body] = putMock.mock.calls[0]!;
    expect(url).toBe("/shifts/day/employees");
    expect([...body.employee_ids].sort()).toEqual(["b", "c"]);
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it("searching only filters the list -- it never drops people from the selection", async () => {
    renderDialog();
    await waitFor(() => expect(box("Ann Assigned")).toBeChecked());
    await userEvent.type(screen.getByPlaceholderText(/search/i), "ben");
    await screen.findByText("Ben Free");
    await waitFor(() => expect(screen.queryByText("Ann Assigned")).not.toBeInTheDocument());
    await userEvent.click(box("Ben Free"));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(putMock).toHaveBeenCalled());
    // Ann was filtered out of view, but she is still on the shift.
    expect([...putMock.mock.calls[0]![1].employee_ids].sort()).toEqual(["a", "b"]);
  });

  it("saving is disabled until the current roster has loaded", async () => {
    getMock.mockImplementation(() => new Promise(() => {})); // never resolves
    renderDialog();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });
});
