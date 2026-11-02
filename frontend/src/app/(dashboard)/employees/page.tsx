"use client";

import { useEffect, useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { UserPlus, Users, UserCheck, Clock, UserX, Download, Upload, FileText, Bookmark, X } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import type { EmployeeListItem } from "@/types";
import { useEmployees, useEmployeeStats, type EmployeeFilters } from "@/services/employee.service";
import { downloadCsv } from "@/services/employeeLifecycle.service";
import apiClient from "@/services/api-client";
import { useAuthStore } from "@/store/auth.store";
import { DataTable } from "@/components/molecules/DataTable";
import { AvatarLabelGroup, Badge, Button, Card, EmptyState, PageHeader, Skeleton, StatusDot } from "@/components/atoms";
import { useRouter } from "next/navigation";

type ViewFilters = Pick<EmployeeFilters, "query" | "department_id" | "branch_id" | "status" | "employment_type">;
interface SavedView { name: string; filters: ViewFilters }
const VIEWS_KEY = "ewmp.employees.views";
const selectCls =
  "h-9 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-2 text-sm outline-none focus:border-[hsl(var(--brand-300))]";
const STATUS_FILTERS = [
  ["active", "Active"], ["probation", "Probation"], ["on_leave", "On leave"],
  ["notice_period", "Notice period"], ["resigned", "Resigned"], ["terminated", "Terminated"],
] as const;
const TYPE_FILTERS = [
  ["full_time", "Full time"], ["part_time", "Part time"], ["contract", "Contract"],
  ["intern", "Intern"], ["freelance", "Freelance"],
] as const;

// Saved views live in this browser only (a personal convenience, not shared data).
function readViews(): SavedView[] {
  try {
    const raw = window.localStorage.getItem(VIEWS_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed.filter((v) => v && typeof v.name === "string" && v.filters) : [];
  } catch {
    return [];
  }
}
function writeViews(views: SavedView[]) {
  try {
    window.localStorage.setItem(VIEWS_KEY, JSON.stringify(views));
  } catch {
    /* storage unavailable (private window): the view just won't persist */
  }
}
const statusConfig: Record<string, { label: string; variant: "success"|"warning"|"error"|"default"|"info" }> = {
  regular:       { label: "Regular",        variant: "success" },
  active:        { label: "Active",        variant: "success" },
  probation:     { label: "Probation",     variant: "info" },
  on_leave:      { label: "On Leave",      variant: "warning" },
  notice_period: { label: "Notice Period", variant: "warning" },
  terminated:    { label: "Terminated",    variant: "error" },
  resigned:      { label: "Resigned",      variant: "error" },
};

function getDisplayStatus(employee: EmployeeListItem) {
  if (employee.job_nature === "permanent") {
    return { label: "Regular", variant: "success" as const };
  }
  return statusConfig[employee.employment_status] ?? {
    label: employee.employment_status,
    variant: "default" as const,
  };
}

function StatCard({ icon: Icon, label, value, colorKey }: { icon: React.ElementType; label: string; value: number; colorKey: string }) {
  const bg: Record<string,string> = { green:"bg-[hsl(var(--success-subtle))]", yellow:"bg-[hsl(var(--warning-subtle))]", red:"bg-[hsl(var(--status-error-bg))]", gray:"bg-[hsl(var(--secondary))]" };
  const fg: Record<string,string> = { green:"text-[hsl(var(--success))]", yellow:"text-[hsl(var(--warning))]", red:"text-[hsl(var(--destructive))]", gray:"text-[hsl(var(--foreground-subtle))]" };
  return (
    <Card>
      <div className="flex items-center gap-3">
        <div className={"flex h-10 w-10 items-center justify-center rounded-md " + (bg[colorKey] ?? bg.gray)}>
          <Icon size={18} className={fg[colorKey] ?? fg.gray} />
        </div>
        <div>
          <p className="font-heading text-xl font-semibold text-[hsl(var(--foreground))]">{value}</p>
          <p className="text-sm text-[hsl(var(--foreground-muted))]">{label}</p>
        </div>
      </div>
    </Card>
  );
}

export default function EmployeesPage() {
  const router = useRouter();
  const [page, setPage] = useState(1);
  const [searchInput, setSearchInput] = useState("");
  const [query, setQuery] = useState("");
  const pageSize = 25;
  const hasPermission = useAuthStore((st) => st.hasPermission);
  const canExport = hasPermission("employees.export");
  const canImport = hasPermission("employees.create");
  const [department, setDepartment] = useState("");
  const [branch, setBranch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [views, setViews] = useState<SavedView[]>([]);
  const [viewName, setViewName] = useState("");
  const [naming, setNaming] = useState(false);
  useEffect(() => setViews(readViews()), []);

  const { data: departments } = useQuery({
    queryKey: ["departments"],
    queryFn: async () => (await apiClient.get("/departments")).data,
  });
  const { data: branches } = useQuery({
    queryKey: ["branches"],
    queryFn: async () => (await apiClient.get("/branches")).data,
  });
  const deptList: { id: string; name: string }[] = departments?.items ?? [];
  const branchList: { id: string; name: string }[] = branches?.items ?? [];

  // Debounce search-as-you-type before it hits the server (bug H10 fix):
  // reset to page 1 whenever the effective search term changes.
  useEffect(() => {
    const t = setTimeout(() => {
      setQuery(searchInput);
      setPage(1);
    }, 300);
    return () => clearTimeout(t);
  }, [searchInput]);

  const active: ViewFilters = {
    query: query || undefined,
    department_id: department || undefined,
    branch_id: branch || undefined,
    status: statusFilter || undefined,
    employment_type: typeFilter || undefined,
  };
  const filters = { page, page_size: pageSize, ...active };
  const anyFilter = Object.values(active).some(Boolean);

  function applyFilters(f: ViewFilters) {
    setDepartment(f.department_id ?? "");
    setBranch(f.branch_id ?? "");
    setStatusFilter(f.status ?? "");
    setTypeFilter(f.employment_type ?? "");
    setSearchInput(f.query ?? "");
    setQuery(f.query ?? "");
    setPage(1);
  }
  function saveView() {
    const name = viewName.trim();
    if (!name) return;
    const next = [...views.filter((v) => v.name !== name), { name, filters: active }];
    setViews(next);
    writeViews(next);
    setViewName("");
    setNaming(false);
  }
  function deleteView(name: string) {
    const next = views.filter((v) => v.name !== name);
    setViews(next);
    writeViews(next);
  }
  const { data, isLoading } = useEmployees(filters);
  const { data: stats, isLoading: statsLoading } = useEmployeeStats();

  const columns: ColumnDef<EmployeeListItem, unknown>[] = [
    {
      id: "employee",
      header: "Employee",
      accessorFn: (r) => r.full_name,
      cell: ({ row }) => {
        const e = row.original;
        return <AvatarLabelGroup name={e.full_name} subtext={e.employee_code} src={e.avatar_url} size="sm" />;
      },
      size: 240,
    },
    {
      id: "status", header: "Status", accessorKey: "employment_status",
      cell: ({ row }) => {
        const cfg = getDisplayStatus(row.original);
        return <Badge variant={cfg.variant}>{cfg.label}</Badge>;
      },
    },
    {
      id: "type", header: "Type", accessorKey: "employment_type",
      cell: ({ getValue }) => <span className="capitalize text-sm text-[hsl(var(--foreground-subtle))]">{getValue<string>().replace("_"," ")}</span>,
    },
    {
      id: "joining", header: "Joined", accessorKey: "date_of_joining",
      cell: ({ getValue }) => <span className="text-sm text-[hsl(var(--foreground-subtle))]">{new Date(getValue<string>()).toLocaleDateString("en-US",{day:"numeric",month:"short",year:"numeric"})}</span>,
    },
    {
      id: "tenure", header: "Tenure", accessorKey: "years_of_service",
      cell: ({ getValue }) => { const y = getValue<number>(); return <span className="text-sm text-[hsl(var(--foreground-subtle))]">{y<1?`${Math.round(y*12)}m`:`${y}y`}</span>; },
    },
    {
      id: "location", header: "Location", accessorKey: "is_remote",
      cell: ({ getValue }) => getValue<boolean>() ? <StatusDot color="blue" label="Remote"/> : <StatusDot color="gray" label="On-site"/>,
    },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Employees"
        description="Manage your workforce, employment details, and org structure."
        action={
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" icon={<FileText size={14}/>} onClick={()=>router.push("/employees/contracts")}>Contracts</Button>
            {canImport && <Button variant="outline" icon={<Upload size={14}/>} onClick={()=>router.push("/employees/import")}>Import</Button>}
            {canExport && (
              <Button variant="outline" icon={<Download size={14}/>} onClick={()=>void downloadCsv("/employees/export", "employees.csv", active)}>
                Export CSV
              </Button>
            )}
            <Button icon={<UserPlus size={15}/>} onClick={()=>router.push("/employees/new")}>Add Employee</Button>
          </div>
        }
      />

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        {statsLoading
          ? Array.from({length:4}).map((_,i) => <Card key={i}><Skeleton className="h-14 w-full"/></Card>)
          : <>
              <StatCard icon={Users}     label="Total Active"  value={stats?.total_active as number ?? 0}  colorKey="green"/>
              <StatCard icon={Clock}     label="On Probation"  value={stats?.on_probation as number ?? 0}  colorKey="yellow"/>
              <StatCard icon={UserCheck} label="On Leave"      value={stats?.on_leave as number ?? 0}      colorKey="gray"/>
              <StatCard icon={UserX}     label="Notice Period" value={stats?.notice_period as number ?? 0} colorKey="red"/>
            </>
        }
      </div>

      <div className="flex flex-wrap items-center gap-2" data-testid="employee-filters">
        <select aria-label="Department filter" className={selectCls} value={department} onChange={(e)=>{setDepartment(e.target.value);setPage(1);}}>
          <option value="">All departments</option>
          {deptList.map((d)=><option key={d.id} value={d.id}>{d.name}</option>)}
        </select>
        <select aria-label="Branch filter" className={selectCls} value={branch} onChange={(e)=>{setBranch(e.target.value);setPage(1);}}>
          <option value="">All branches</option>
          {branchList.map((b)=><option key={b.id} value={b.id}>{b.name}</option>)}
        </select>
        <select aria-label="Status filter" className={selectCls} value={statusFilter} onChange={(e)=>{setStatusFilter(e.target.value);setPage(1);}}>
          <option value="">All statuses</option>
          {STATUS_FILTERS.map(([v,l])=><option key={v} value={v}>{l}</option>)}
        </select>
        <select aria-label="Type filter" className={selectCls} value={typeFilter} onChange={(e)=>{setTypeFilter(e.target.value);setPage(1);}}>
          <option value="">All types</option>
          {TYPE_FILTERS.map(([v,l])=><option key={v} value={v}>{l}</option>)}
        </select>
        {anyFilter && (
          <button type="button" className="text-xs text-[hsl(var(--primary))] underline" onClick={()=>applyFilters({})}>Clear filters</button>
        )}
        <span className="mx-1 hidden h-5 w-px bg-[hsl(var(--border))] sm:block" />
        {views.map((v)=>(
          <span key={v.name} className="inline-flex items-center gap-1 rounded-full border border-[hsl(var(--border))] pl-2.5 pr-1 text-xs">
            <button type="button" className="py-1 font-medium" onClick={()=>applyFilters(v.filters)}>{v.name}</button>
            <button type="button" aria-label={`Delete view ${v.name}`} className="rounded-full p-0.5 hover:bg-[hsl(var(--accent))]" onClick={()=>deleteView(v.name)}><X size={11}/></button>
          </span>
        ))}
        {naming ? (
          <span className="inline-flex items-center gap-1">
            <input aria-label="View name" autoFocus className={selectCls+" w-36"} placeholder="View name" value={viewName}
              onChange={(e)=>setViewName(e.target.value)} onKeyDown={(e)=>{if(e.key==="Enter")saveView();}} />
            <Button size="sm" disabled={!viewName.trim()} onClick={saveView}>Save</Button>
          </span>
        ) : (
          <Button size="sm" variant="outline" icon={<Bookmark size={12}/>} disabled={!anyFilter} onClick={()=>setNaming(true)}>Save view</Button>
        )}
      </div>

      <DataTable
        data={data?.items ?? []}
        columns={columns}
        isLoading={isLoading}
        searchPlaceholder="Search employees..."
        onRowClick={(row) => router.push(`/employees/${row.id}`)}
        manual={{
          pageIndex: page - 1,
          pageCount: data?.total_pages ?? 1,
          totalRows: data?.total ?? 0,
          onPageChange: (pageIndex) => setPage(pageIndex + 1),
          searchValue: searchInput,
          onSearchChange: setSearchInput,
        }}
        emptyState={
          <EmptyState
            icon={Users}
            title="No employees yet"
            description="Add your first employee to get started."
            action={<Button icon={<UserPlus size={14}/>} onClick={()=>router.push("/employees/new")}>Add First Employee</Button>}
          />
        }
      />

    </div>
  );
}