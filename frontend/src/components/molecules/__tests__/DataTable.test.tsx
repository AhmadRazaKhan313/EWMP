/**
 * Regression tests for DataTable's manual (server-driven) mode — the H10 fix.
 *
 * DataTable used to be 100% client-side: pagination and search only ever
 * operated on whatever `data` array was passed in. Combined with the
 * Employees page always fetching page 1 / 25 and never changing that,
 * employees beyond the first 25 were unreachable and unsearchable.
 *
 * These tests cover the new opt-in `manual` prop in isolation. A separate
 * `EmployeesPage`-plumbing test file below (in
 * `employees/__tests__/EmployeesPage.test.tsx`) covers that the page
 * actually wires it up.
 *
 * Run:  cd frontend && npm test -- DataTable
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ColumnDef } from "@tanstack/react-table";
import { DataTable } from "../DataTable";

interface Row {
  id: string;
  name: string;
}

const columns: ColumnDef<Row, unknown>[] = [
  { header: "Name", accessorKey: "name" },
];

function rows(n: number): Row[] {
  return Array.from({ length: n }, (_, i) => ({ id: String(i), name: `Person ${i}` }));
}

describe("DataTable — manual (server-driven) mode", () => {
  it("in manual mode, the footer uses server-provided totals, not data.length", () => {
    render(
      <DataTable
        data={rows(25)} // just this page's rows
        columns={columns}
        manual={{
          pageIndex: 2, // page 3 (0-based)
          pageCount: 5,
          totalRows: 123, // full org headcount, far beyond the 25 rows on this page
          onPageChange: vi.fn(),
          searchValue: "",
          onSearchChange: vi.fn(),
        }}
      />,
    );
    expect(screen.getByText(/123/)).toBeInTheDocument();
    expect(screen.getByText(/page 3 of 5/i)).toBeInTheDocument();
  });

  it("Next/Previous call onPageChange instead of paginating client-side", async () => {
    const onPageChange = vi.fn();
    render(
      <DataTable
        data={rows(25)}
        columns={columns}
        manual={{
          pageIndex: 1,
          pageCount: 10,
          totalRows: 250,
          onPageChange,
          searchValue: "",
          onSearchChange: vi.fn(),
        }}
      />,
    );
    const user = userEvent.setup();
    const buttons = screen.getAllByRole("button");
    // Prev is the first icon button, Next the second, in the pagination footer.
    await user.click(buttons[buttons.length - 1]!);
    expect(onPageChange).toHaveBeenCalledWith(2);
  });

  it("Previous is disabled on the first page and Next disabled on the last, per server pageCount", () => {
    const { rerender } = render(
      <DataTable
        data={rows(25)}
        columns={columns}
        manual={{ pageIndex: 0, pageCount: 3, totalRows: 75, onPageChange: vi.fn(), searchValue: "", onSearchChange: vi.fn() }}
      />,
    );
    const buttons = screen.getAllByRole("button");
    expect(buttons[buttons.length - 2]!).toBeDisabled(); // Prev

    rerender(
      <DataTable
        data={rows(25)}
        columns={columns}
        manual={{ pageIndex: 2, pageCount: 3, totalRows: 75, onPageChange: vi.fn(), searchValue: "", onSearchChange: vi.fn() }}
      />,
    );
    const buttons2 = screen.getAllByRole("button");
    expect(buttons2[buttons2.length - 1]!).toBeDisabled(); // Next
  });

  it("search box reflects manual.searchValue and calls onSearchChange (not internal filtering)", async () => {
    const onSearchChange = vi.fn();
    render(
      <DataTable
        data={rows(25)}
        columns={columns}
        searchPlaceholder="Search employees..."
        manual={{ pageIndex: 0, pageCount: 5, totalRows: 100, onPageChange: vi.fn(), searchValue: "", onSearchChange }}
      />,
    );
    const user = userEvent.setup();
    const input = screen.getByPlaceholderText("Search employees...");
    await user.type(input, "a");
    expect(onSearchChange).toHaveBeenCalledWith("a");
  });

  it("still shows every row passed in (no client-side re-slicing of an already-paginated server page)", () => {
    render(
      <DataTable
        data={rows(25)}
        columns={columns}
        manual={{ pageIndex: 0, pageCount: 5, totalRows: 100, onPageChange: vi.fn(), searchValue: "", onSearchChange: vi.fn() }}
      />,
    );
    expect(screen.getByText("Person 0")).toBeInTheDocument();
    expect(screen.getByText("Person 24")).toBeInTheDocument();
  });
});

describe("DataTable — default (client-side) mode is unaffected (regression safety)", () => {
  it("without `manual`, pagination and counts are still computed from `data` itself", () => {
    render(<DataTable data={rows(5)} columns={columns} />);
    // 5 rows, one page — footer should reflect the full local array, not any server total.
    const footer = screen.getByText(/results/i).closest("div");
    expect(footer).toHaveTextContent("1–5");
    expect(footer).toHaveTextContent("of");
  });

  it("without `manual`, typing in search filters the local data client-side", async () => {
    render(<DataTable data={[{ id: "1", name: "Alice" }, { id: "2", name: "Bob" }]} columns={columns} />);
    const user = userEvent.setup();
    await user.type(screen.getByPlaceholderText("Search…"), "Alice");
    expect(screen.getByText("Alice")).toBeInTheDocument();
    expect(screen.queryByText("Bob")).not.toBeInTheDocument();
  });
});
