"use client";

import { useEffect, useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { UserPlus, Users, UserCheck, Clock, UserX } from "lucide-react";
import type { EmployeeListItem } from "@/types";
import { useEmployees, useEmployeeStats } from "@/services/employee.service";
import { DataTable } from "@/components/molecules/DataTable";
import { Badge, Button, Card, EmptyState, PageHeader, Skeleton, StatusDot } from "@/components/atoms";
import { EmployeeDrawer } from "@/components/organisms/EmployeeDrawer";
import { useRouter } from "next/navigation";

const statusConfig: Record<string, { label: string; variant: "success"|"warning"|"error"|"default"|"info" }> = {
  active:        { label: "Active",        variant: "success" },
  probation:     { label: "Probation",     variant: "info" },
  on_leave:      { label: "On Leave",      variant: "warning" },
  notice_period: { label: "Notice Period", variant: "warning" },
  terminated:    { label: "Terminated",    variant: "error" },
  resigned:      { label: "Resigned",      variant: "error" },
};

function StatCard({ icon: Icon, label, value, colorKey }: { icon: React.ElementType; label: string; value: number; colorKey: string }) {
  const bg: Record<string,string> = { green:"bg-[hsl(var(--success-subtle))]", yellow:"bg-[hsl(var(--warning-subtle))]", red:"bg-[hsl(var(--status-error-bg))]", gray:"bg-[hsl(var(--secondary))]" };
  const fg: Record<string,string> = { green:"text-[hsl(var(--success))]", yellow:"text-[hsl(var(--warning))]", red:"text-[hsl(var(--destructive))]", gray:"text-[hsl(var(--foreground-subtle))]" };
  return (
    <Card>
      <div className="flex items-center gap-3">
        <div className={"flex h-9 w-9 items-center justify-center rounded-lg " + (bg[colorKey] ?? bg.gray)}>
          <Icon size={16} className={fg[colorKey] ?? fg.gray} />
        </div>
        <div>
          <p className="text-xl font-semibold font-heading">{value}</p>
          <p className="text-xs text-[hsl(var(--foreground-muted))]">{label}</p>
        </div>
      </div>
    </Card>
  );
}

export default function EmployeesPage() {
  const router = useRouter();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [page, setPage] = useState(1);
  const [searchInput, setSearchInput] = useState("");
  const [query, setQuery] = useState("");
  const pageSize = 25;

  // Debounce search-as-you-type before it hits the server (bug H10 fix):
  // reset to page 1 whenever the effective search term changes.
  useEffect(() => {
    const t = setTimeout(() => {
      setQuery(searchInput);
      setPage(1);
    }, 300);
    return () => clearTimeout(t);
  }, [searchInput]);

  const filters = { page, page_size: pageSize, query: query || undefined };
  const { data, isLoading } = useEmployees(filters);
  const { data: stats, isLoading: statsLoading } = useEmployeeStats();

  const columns: ColumnDef<EmployeeListItem, unknown>[] = [
    {
      id: "employee",
      header: "Employee",
      accessorFn: (r) => r.full_name,
      cell: ({ row }) => {
        const e = row.original;
        const initials = ((e.first_name||"")[0]??"") + ((e.last_name||"")[0]??"");
        return (
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[hsl(var(--secondary))] text-[11px] font-bold text-[hsl(var(--foreground-subtle))]">
              {initials.toUpperCase()}
            </div>
            <div>
              <p className="font-medium leading-tight">{e.full_name}</p>
              <p className="font-mono text-[11px] text-[hsl(var(--foreground-muted))]">{e.employee_code}</p>
            </div>
          </div>
        );
      },
      size: 220,
    },
    {
      id: "status", header: "Status", accessorKey: "employment_status",
      cell: ({ getValue }) => {
        const s = getValue<string>();
        const cfg = statusConfig[s] ?? { label: s, variant: "default" as const };
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
        action={<Button icon={<UserPlus size={15}/>} onClick={()=>setDrawerOpen(true)}>Add Employee</Button>}
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
            action={<Button icon={<UserPlus size={14}/>} onClick={()=>setDrawerOpen(true)}>Add First Employee</Button>}
          />
        }
      />

      <EmployeeDrawer open={drawerOpen} onClose={()=>setDrawerOpen(false)}/>
    </div>
  );
}