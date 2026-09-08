"use client";
import { useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { Headphones, Plus, Clock, CheckCircle, AlertCircle, XCircle, MessageSquare } from "lucide-react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import apiClient from "@/services/api-client";
import { DataTable } from "@/components/molecules/DataTable";
import { Badge, Button, Card, EmptyState, PageHeader } from "@/components/atoms";

const priorityConfig: Record<string,{label:string;variant:"success"|"warning"|"error"|"default"|"info"}> = {
  low:      {label:"Low",      variant:"default"},
  medium:   {label:"Medium",   variant:"info"},
  high:     {label:"High",     variant:"warning"},
  critical: {label:"Critical", variant:"error"},
};
const statusConfig: Record<string,{label:string;variant:"success"|"warning"|"error"|"default"|"info"}> = {
  open:        {label:"Open",        variant:"info"},
  in_progress: {label:"In Progress", variant:"warning"},
  pending:     {label:"Pending",     variant:"default"},
  resolved:    {label:"Resolved",    variant:"success"},
  closed:      {label:"Closed",      variant:"default"},
};

export default function HelpdeskPage() {
  const qc = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [tab, setTab] = useState<"all"|"open"|"in_progress"|"resolved">("all");
  const [form, setForm] = useState({ title:"", description:"", priority:"medium", category:"Hardware" });

  const { data, isLoading } = useQuery({
    queryKey: ["tickets", tab],
    queryFn: async () => {
      const params = tab !== "all" ? { status: tab } : {};
      const { data } = await apiClient.get("/helpdesk/tickets", { params });
      return data;
    }
  });

  const create = useMutation({
    mutationFn: (b: object) => apiClient.post("/helpdesk/tickets", b),
    onSuccess: () => { toast.success("Ticket created"); void qc.invalidateQueries({ queryKey: ["tickets"] }); setShowForm(false); setForm({title:"",description:"",priority:"medium",category:"Hardware"}); },
    onError: () => toast.error("Failed to create ticket"),
  });

  const updateStatus = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) => apiClient.patch(`/helpdesk/tickets/${id}`, { status }),
    onSuccess: () => { toast.success("Status updated"); void qc.invalidateQueries({ queryKey: ["tickets"] }); },
  });

  const inp = "w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]";
  const tickets = data?.items ?? [];
  const open = tickets.filter((t:any) => t.status === "open").length;
  const inProg = tickets.filter((t:any) => t.status === "in_progress").length;
  const resolved = tickets.filter((t:any) => t.status === "resolved").length;

  const columns: ColumnDef<any, unknown>[] = [
    { header: "Ticket", accessorKey: "title", cell: ({row}) => (
      <div>
        <div className="flex items-center gap-2">
          <span className="font-mono text-[10px] text-[hsl(var(--foreground-muted))] bg-[hsl(var(--secondary))] px-1.5 py-0.5 rounded">#{row.original.ticket_number}</span>
        </div>
        <p className="font-medium text-sm mt-0.5">{row.original.title}</p>
        <p className="text-xs text-[hsl(var(--foreground-muted))] truncate max-w-xs">{row.original.description}</p>
      </div>
    ), size: 280 },
    { header: "Category", accessorKey: "category", cell: ({getValue}) => <span className="text-sm text-[hsl(var(--foreground-subtle))]">{getValue<string>()}</span> },
    { header: "Priority", accessorKey: "priority", cell: ({getValue}) => { const p = getValue<string>(); const cfg = priorityConfig[p] ?? {label:p,variant:"default" as const}; return <Badge variant={cfg.variant}>{cfg.label}</Badge>; } },
    { header: "Status", accessorKey: "status", cell: ({getValue}) => { const s = getValue<string>(); const cfg = statusConfig[s] ?? {label:s,variant:"default" as const}; return <Badge variant={cfg.variant}>{cfg.label}</Badge>; } },
    { header: "Created", accessorKey: "created_at", cell: ({getValue}) => <span className="text-xs text-[hsl(var(--foreground-muted))]">{new Date(getValue<string>()).toLocaleDateString("en-US",{day:"numeric",month:"short",year:"numeric"})}</span> },
    { id: "actions", header: "", cell: ({row}) => {
      const t = row.original;
      if (t.status === "resolved" || t.status === "closed") return null;
      return (
        <div className="flex gap-1">
          {t.status === "open" && <button onClick={() => updateStatus.mutate({id:t.id,status:"in_progress"})} className="text-xs px-2 py-1 rounded bg-[hsl(var(--warning-subtle))] text-[hsl(var(--warning))] hover:opacity-80">Assign</button>}
          {t.status === "in_progress" && <button onClick={() => updateStatus.mutate({id:t.id,status:"resolved"})} className="text-xs px-2 py-1 rounded bg-[hsl(var(--success-subtle))] text-[hsl(var(--success))] hover:opacity-80">Resolve</button>}
        </div>
      );
    }, size: 90 },
  ];

  return (
    <div className="space-y-6">
      <PageHeader title="IT Helpdesk" description="Manage support tickets and IT requests." action={<Button icon={<Plus size={15}/>} onClick={() => setShowForm(true)}>New Ticket</Button>}/>

      <div className="grid grid-cols-4 gap-4">
        <Card><div className="flex items-center gap-3"><div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[hsl(var(--info-subtle))]"><MessageSquare size={16} className="text-[hsl(var(--info))]"/></div><div><p className="text-2xl font-semibold font-heading">{open}</p><p className="text-xs text-[hsl(var(--foreground-muted))]">Open</p></div></div></Card>
        <Card><div className="flex items-center gap-3"><div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[hsl(var(--warning-subtle))]"><Clock size={16} className="text-[hsl(var(--warning))]"/></div><div><p className="text-2xl font-semibold font-heading">{inProg}</p><p className="text-xs text-[hsl(var(--foreground-muted))]">In Progress</p></div></div></Card>
        <Card><div className="flex items-center gap-3"><div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[hsl(var(--success-subtle))]"><CheckCircle size={16} className="text-[hsl(var(--success))]"/></div><div><p className="text-2xl font-semibold font-heading">{resolved}</p><p className="text-xs text-[hsl(var(--foreground-muted))]">Resolved</p></div></div></Card>
        <Card><div className="flex items-center gap-3"><div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[hsl(var(--status-error-bg))]"><AlertCircle size={16} className="text-[hsl(var(--destructive))]"/></div><div><p className="text-2xl font-semibold font-heading">{tickets.filter((t:any)=>t.priority==="critical").length}</p><p className="text-xs text-[hsl(var(--foreground-muted))]">Critical</p></div></div></Card>
      </div>

      {showForm && (
        <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-5 space-y-4">
          <h3 className="font-heading text-sm font-semibold">New Support Ticket</h3>
          <div><label className="block text-xs font-medium mb-1">Title *</label><input value={form.title} onChange={e=>setForm(f=>({...f,title:e.target.value}))} placeholder="Brief description of the issue" className={inp}/></div>
          <div className="grid grid-cols-2 gap-4">
            <div><label className="block text-xs font-medium mb-1">Category</label><select value={form.category} onChange={e=>setForm(f=>({...f,category:e.target.value}))} className={inp}><option>Hardware</option><option>Software</option><option>Network</option><option>Access</option><option>Email</option><option>Other</option></select></div>
            <div><label className="block text-xs font-medium mb-1">Priority</label><select value={form.priority} onChange={e=>setForm(f=>({...f,priority:e.target.value}))} className={inp}><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option><option value="critical">Critical</option></select></div>
          </div>
          <div><label className="block text-xs font-medium mb-1">Description</label><textarea value={form.description} onChange={e=>setForm(f=>({...f,description:e.target.value}))} rows={3} placeholder="Detailed description of the issue..." className={inp+" resize-none"}/></div>
          <div className="flex justify-end gap-2">
            <Button variant="outline" size="sm" onClick={() => setShowForm(false)}>Cancel</Button>
            <Button size="sm" disabled={!form.title || create.isPending} onClick={() => create.mutate(form)}>{create.isPending ? "Submitting..." : "Submit Ticket"}</Button>
          </div>
        </div>
      )}

      <div className="flex gap-1 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--background-subtle))] p-1 w-fit">
        {(["all","open","in_progress","resolved"] as const).map(t => (
          <button key={t} onClick={() => setTab(t)} className={"rounded-md px-3 py-1.5 text-sm font-medium transition-colors capitalize " + (tab===t ? "bg-[hsl(var(--background))] shadow-sm text-[hsl(var(--foreground))]" : "text-[hsl(var(--foreground-muted))] hover:text-[hsl(var(--foreground))]")}>
            {t.replace("_"," ")}
          </button>
        ))}
      </div>

      <DataTable
        data={tickets}
        columns={columns}
        isLoading={isLoading}
        searchPlaceholder="Search tickets..."
        emptyState={<EmptyState icon={Headphones} title="No tickets" description="No support tickets found." action={<Button icon={<Plus size={14}/>} onClick={() => setShowForm(true)}>Create Ticket</Button>}/>}
      />
    </div>
  );
}