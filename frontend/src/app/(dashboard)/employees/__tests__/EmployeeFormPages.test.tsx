/** Add / Edit Employee are real pages that render the shared form (no drawer overlay). */
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }), useParams: () => ({ id: "e1" }) }));
vi.mock("@/components/organisms/EmployeeDrawer", () => ({
  EmployeeDrawer: (p: { open: boolean; variant?: string; employeeId?: string; onClose: () => void }) => (
    <button onClick={p.onClose}>{`form variant=${p.variant} open=${p.open} id=${p.employeeId ?? "none"}`}</button>
  ),
}));

import NewEmployeePage from "../new/page";
import EditEmployeePage from "../[id]/edit/page";

describe("employee form pages", () => {
  it("/employees/new renders the form as a page and closes back to the list", () => {
    render(<NewEmployeePage />);
    const b = screen.getByText("form variant=page open=true id=none");
    b.click();
    expect(push).toHaveBeenCalledWith("/employees");
  });

  it("/employees/[id]/edit renders the same form prefilled and closes back to the profile", async () => {
    render(<EditEmployeePage />);
    const b = await screen.findByText("form variant=page open=true id=e1");
    b.click();
    expect(push).toHaveBeenCalledWith("/employees/e1");
    expect((screen.getByText("Back to profile").closest("a") as HTMLAnchorElement).getAttribute("href")).toBe("/employees/e1");
  });
});
