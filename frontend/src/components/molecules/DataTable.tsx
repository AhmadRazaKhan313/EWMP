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
      <div className="flex items-center gap-2">
        {/* Search */}
        <div className="relative flex-1">
          <Search
            size={14}
            className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[hsl(var(--foreground-muted))]"
          />
          <input
            value={globalFilter}
            onChange={(e) => setGlobalFilter(e.target.value)}
            placeholder={searchPlaceholder}
            className={cn(
              "h-9 w-full max-w-xs rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))]",
              "pl-8 pr-3 text-sm outline-none placeholder:text-[hsl(var(--foreground-muted))]",
              "focus:ring-2 focus:ring-[hsl(var(--ring))] focus:ring-offset-1",
              "hover:border-[hsl(var(--border-strong))]",
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
              "flex h-9 items-center gap-1.5 rounded-md border border-[hsl(var(--border))] px-3 text-sm",
              "hover:bg-[hsl(var(--accent))] transition-colors",
            )}
          >
            <Settings2 size={14} />
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
                <tr key={hg.id} className="border-b border-[hsl(var(--border))] bg-[hsl(var(--background-subtle))]">
                  {hg.headers.map((header) => (
                    <th
                      key={header.id}
                      className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-[hsl(var(--foreground-muted))]"
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

            <tbody className="divide-y divide-[hsl(var(--border))]">
              {isLoading ? (
                Array.from({ length: 8 }).map((_, i) => (
                  <tr key={i}>
                    {columns.map((_, j) => (
                      <td key={j} className="px-4 py-3">
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
                      <td key={cell.id} className="px-4 py-3">
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </td>
                    ))}
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        <div className="flex items-center justify-between border-t border-[hsl(var(--border))] px-4 py-3">
          <div className="text-xs text-[hsl(var(--foreground-muted))]">
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

          <div className="flex items-center gap-1">
            <button
              onClick={goPrev}
              disabled={!canPrev}
              className="flex h-7 w-7 items-center justify-center rounded-md border border-[hsl(var(--border))] hover:bg-[hsl(var(--accent))] disabled:opacity-40"
            >
              <ChevronLeft size={13} />
            </button>
            <span className="px-2 text-xs font-medium">
              Page {currentPageLabel} of {pageCountLabel}
            </span>
            <button
              onClick={goNext}
              disabled={!canNext}
              className="flex h-7 w-7 items-center justify-center rounded-md border border-[hsl(var(--border))] hover:bg-[hsl(var(--accent))] disabled:opacity-40"
            >
              <ChevronRight size={13} />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}