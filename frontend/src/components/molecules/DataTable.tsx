"use client";

/**
 * DataTable molecule.
 *
 * Generic TanStack Table wrapper used by every list page (Employees, Devices, Assets…).
 * Features: column sorting, global search, pagination, column visibility, row selection.
 */

import { useState } from "react";
import {
  type ColumnDef,
  type SortingState,
  type VisibilityState,
  type RowSelectionState,
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  useReactTable,
} from "@tanstack/react-table";
import {
  ChevronUp, ChevronDown, ChevronsUpDown,
  ChevronLeft, ChevronRight, Search, Settings2,
} from "lucide-react";
import { cn } from "@/utils/cn";
import { Skeleton } from "@/components/atoms";

interface DataTableProps<TData> {
  data: TData[];
  columns: ColumnDef<TData, unknown>[];
  isLoading?: boolean;
  searchPlaceholder?: string;
  pageSize?: number;
  onRowClick?: (row: TData) => void;
  toolbar?: React.ReactNode;
  emptyState?: React.ReactNode;
  /**
   * Server-driven pagination + search (bug H10). When omitted, DataTable
   * behaves exactly as before: `data` is treated as the full result set and
   * paginated/searched client-side. Pass this when `data` is already just
   * one page fetched from the server — every other page using DataTable
   * today (devices, assets, …) is unaffected either way.
   */
  manual?: {
    pageIndex: number; // 0-based
    pageCount: number;
    totalRows: number;
    onPageChange: (pageIndex: number) => void;
    searchValue: string;
    onSearchChange: (value: string) => void;
  };
}

export function DataTable<TData>({
  data,
  columns,
  isLoading,
  searchPlaceholder = "Search…",
  pageSize = 25,
  onRowClick,
  toolbar,
  emptyState,
  manual,
}: DataTableProps<TData>) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const [localGlobalFilter, setLocalGlobalFilter] = useState("");
  const [columnVisibility, setColumnVisibility] = useState<VisibilityState>({});
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
  const [showColMenu, setShowColMenu] = useState(false);

  // In manual mode `data` is already the current page/search result from the
  // server, so we skip client-side filtering/pagination row models entirely
  // rather than re-filtering/re-paginating an already-scoped 25-row slice.
  const globalFilter = manual ? manual.searchValue : localGlobalFilter;
  const setGlobalFilter = manual ? manual.onSearchChange : setLocalGlobalFilter;

  const table = useReactTable({
    data,
    columns,
    state: manual
      ? { sorting, columnVisibility, rowSelection }
      : { sorting, globalFilter, columnVisibility, rowSelection },
    onSortingChange: setSorting,
    onColumnVisibilityChange: setColumnVisibility,
    onRowSelectionChange: setRowSelection,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    ...(manual
      ? {}
      : {
          onGlobalFilterChange: setLocalGlobalFilter,
          getFilteredRowModel: getFilteredRowModel(),
          getPaginationRowModel: getPaginationRowModel(),
          initialState: { pagination: { pageSize } },
        }),
  });

  const selectedCount = Object.keys(rowSelection).length;

  const rangeStart = manual ? manual.pageIndex * pageSize + 1 : table.getState().pagination.pageIndex * pageSize + 1;
  const rangeEnd = manual
    ? Math.min((manual.pageIndex + 1) * pageSize, manual.totalRows)
    : Math.min((table.getState().pagination.pageIndex + 1) * pageSize, table.getFilteredRowModel().rows.length);
  const totalCount = manual ? manual.totalRows : table.getFilteredRowModel().rows.length;
  const currentPageLabel = manual ? manual.pageIndex + 1 : table.getState().pagination.pageIndex + 1;
  const pageCountLabel = manual ? Math.max(1, manual.pageCount) : table.getPageCount();
  const canPrev = manual ? manual.pageIndex > 0 : table.getCanPreviousPage();
  const canNext = manual ? manual.pageIndex + 1 < manual.pageCount : table.getCanNextPage();
  const goPrev = () => (manual ? manual.onPageChange(manual.pageIndex - 1) : table.previousPage());
  const goNext = () => (manual ? manual.onPageChange(manual.pageIndex + 1) : table.nextPage());

  return (
    <div className="flex flex-col gap-3">
      {/* Toolbar */}
      <div className="flex items-center gap-3">
        {/* Search */}
        <div className="relative flex-1">
          <Search
            size={20}
            className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[hsl(var(--foreground-muted))]"
          />
          <input
            value={globalFilter}
            onChange={(e) => setGlobalFilter(e.target.value)}
            placeholder={searchPlaceholder}
            className={cn(
              "h-10 w-full max-w-xs rounded-md border border-[hsl(var(--border-strong))] bg-[hsl(var(--card))]",
              "pl-11 pr-3.5 text-sm shadow-[var(--shadow-xs)] outline-none placeholder:text-[hsl(var(--foreground-muted))]",
              "focus:border-[hsl(var(--brand-300))] focus:ring-4 focus:ring-[hsl(var(--brand-100))]",
            )}
          />
        </div>

        {/* Selected count */}
        {selectedCount > 0 && (
          <span className="text-xs text-[hsl(var(--foreground-muted))]">
            {selectedCount} selected
          </span>
        )}

        {/* Extra toolbar content */}
        {toolbar}

        {/* Column visibility toggle */}
        <div className="relative">
          <button
            onClick={() => setShowColMenu((v) => !v)}
            className={cn(
              "flex h-10 items-center gap-1.5 rounded-md border border-[hsl(var(--border-strong))] bg-[hsl(var(--card))] px-3.5 text-sm font-semibold",
              "text-[hsl(var(--foreground-subtle))] shadow-[var(--shadow-xs)] hover:bg-[hsl(var(--background-subtle))] transition-colors",
            )}
          >
            <Settings2 size={18} />
            <span className="hidden sm:inline">View</span>
          </button>

          {showColMenu && (
            <div className="absolute right-0 top-full z-50 mt-1 w-44 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--background))] py-1 shadow-[var(--shadow-md)]">
              {table.getAllColumns()
                .filter((c) => c.getCanHide())
                .map((col) => (
                  <label
                    key={col.id}
                    className="flex cursor-pointer items-center gap-2.5 px-3 py-1.5 text-sm hover:bg-[hsl(var(--accent))]"
                  >
                    <input
                      type="checkbox"
                      checked={col.getIsVisible()}
                      onChange={col.getToggleVisibilityHandler()}
                      className="rounded"
                    />
                    {col.id}
                  </label>
                ))}
            </div>
          )}
        </div>
      </div>

      {/* Table */}
      <div className="overflow-hidden rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] shadow-[var(--shadow-xs)]">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              {table.getHeaderGroups().map((hg) => (
                <tr key={hg.id} className="h-11 border-b border-[hsl(var(--border))] bg-[hsl(var(--background-subtle))]">
                  {hg.headers.map((header) => (
                    <th
                      key={header.id}
                      className="px-6 py-3 text-left text-xs font-semibold text-[hsl(var(--muted-foreground))]"
                      style={{ width: header.getSize() !== 150 ? header.getSize() : undefined }}
                    >
                      {header.isPlaceholder ? null : (
                        <div
                          className={cn(
                            "flex items-center gap-1",
                            header.column.getCanSort() && "cursor-pointer select-none hover:text-[hsl(var(--foreground))]",
                          )}
                          onClick={header.column.getToggleSortingHandler()}
                        >
                          {flexRender(header.column.columnDef.header, header.getContext())}
                          {header.column.getCanSort() && (
                            <span className="ml-0.5">
                              {header.column.getIsSorted() === "asc" ? (
                                <ChevronUp size={12} />
                              ) : header.column.getIsSorted() === "desc" ? (
                                <ChevronDown size={12} />
                              ) : (
                                <ChevronsUpDown size={12} className="opacity-40" />
                              )}
                            </span>
                          )}
                        </div>
                      )}
                    </th>
                  ))}
                </tr>
              ))}
            </thead>

            <tbody className="divide-y divide-[hsl(var(--border))] text-[hsl(var(--foreground-muted))]">
              {isLoading ? (
                Array.from({ length: 8 }).map((_, i) => (
                  <tr key={i}>
                    {columns.map((_, j) => (
                      <td key={j} className="px-6 py-4">
                        <Skeleton className="h-5 w-full" />
                      </td>
                    ))}
                  </tr>
                ))
              ) : table.getRowModel().rows.length === 0 ? (
                <tr>
                  <td colSpan={columns.length} className="py-2">
                    {emptyState ?? (
                      <div className="flex items-center justify-center py-12 text-sm text-[hsl(var(--foreground-muted))]">
                        No results found.
                      </div>
                    )}
                  </td>
                </tr>
              ) : (
                table.getRowModel().rows.map((row) => (
                  <tr
                    key={row.id}
                    onClick={() => onRowClick?.(row.original)}
                    className={cn(
                      "transition-colors hover:bg-[hsl(var(--background-subtle))]",
                      onRowClick && "cursor-pointer",
                      row.getIsSelected() && "bg-[hsl(var(--accent))]",
                    )}
                  >
                    {row.getVisibleCells().map((cell) => (
                      <td key={cell.id} className="px-6 py-4">
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </td>
                    ))}
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination — Untitled UI "card minimal, center aligned": Previous | Page X of Y | Next */}
        <div className="flex items-center gap-3 border-t border-[hsl(var(--border))] px-6 pb-4 pt-3">
          <div className="flex-1 text-xs text-[hsl(var(--foreground-muted))]">
            {isLoading ? (
              <Skeleton className="h-4 w-32" />
            ) : (
              <>
                Showing{" "}
                <span className="font-medium text-[hsl(var(--foreground))]">
                  {totalCount === 0 ? 0 : rangeStart}–{rangeEnd}
                </span>{" "}
                of{" "}
                <span className="font-medium text-[hsl(var(--foreground))]">
                  {totalCount}
                </span>{" "}
                results
              </>
            )}
          </div>

          <span className="text-sm font-medium text-[hsl(var(--foreground-subtle))]">
            Page {currentPageLabel} of {pageCountLabel}
          </span>

          <div className="flex flex-1 items-center justify-end gap-3">
            <button
              onClick={goPrev}
              disabled={!canPrev}
              aria-label="Previous page"
              className="flex h-9 items-center gap-1 rounded-md border border-[hsl(var(--border-strong))] bg-[hsl(var(--card))] px-3 text-sm font-semibold text-[hsl(var(--foreground-subtle))] shadow-[var(--shadow-xs)] hover:bg-[hsl(var(--background-subtle))] disabled:cursor-not-allowed disabled:opacity-50"
            >
              <ChevronLeft size={16} />
              <span className="hidden sm:inline">Previous</span>
            </button>
            <button
              onClick={goNext}
              disabled={!canNext}
              aria-label="Next page"
              className="flex h-9 items-center gap-1 rounded-md border border-[hsl(var(--border-strong))] bg-[hsl(var(--card))] px-3 text-sm font-semibold text-[hsl(var(--foreground-subtle))] shadow-[var(--shadow-xs)] hover:bg-[hsl(var(--background-subtle))] disabled:cursor-not-allowed disabled:opacity-50"
            >
              <span className="hidden sm:inline">Next</span>
              <ChevronRight size={16} />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}