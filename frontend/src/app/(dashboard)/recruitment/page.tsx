"use client";
import { useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { UserSearch, Plus, Briefcase, Users, Clock, CheckCircle } from "lucide-react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import apiClient from "@/services/api-client";
import { DataTable } from "@/components/molecules/DataTable";
import { Badge, Button, Card, EmptyState, PageHeader } from "@/components/atoms";

const jobStatusConfig: Record<string, {label:string;variant:"success"|"warning"|"error"|"default"|"info"}> = {
  draft:     {label:"Draft",     variant:"default"},
  open:      {label:"Open",      variant:"success"},
  paused:    {label:"Paused",    variant:"warning"},
  closed:    {label:"Closed",    variant:"error"},
  cancelled: {label:"Cancelled", variant:"error"},
};
const appStatusConfig: Record<string, {label:string;variant:"success"|"warning"|"error"|"default"|"info"}> = {
  applied:   {label:"Applied",   variant:"default"},
  screening: {label:"Screening", variant:"info"},
  interview: {label:"Interview", variant:"warning"},
  offer:     {label:"Offer",     variant:"success"},
  hired:     {label:"Hired",     variant:"success"},
  rejected:  {label:"Rejected",  variant:"error"},
};

export default function RecruitmentPage() {
  const qc = useQueryClient();
  const [tab, setTab] = useState<"jobs"|"applicants">("jobs");
  const [showJobForm, setShowJobForm] = useState(false);
  const [jobForm, setJobForm] = useState({ title:"", employment_type:"full_time", location:"", is_remote:false, openings:1, salary_min:"", salary_max:"", currency:"USD" });

  const { data: jobsData, isLoading: jobsLoading } = useQuery({ queryKey:["jobs"], queryFn: async () => { const {data} = await apiClient.get("/recruitment/jobs"); return data; }});
  const { data: appsData, isLoading: appsLoading } = useQuery({ queryKey:["applicants"], queryFn: async () => { const {data} = await apiClient.get("/recruitment/applicants"); return data; }});

  const createJob = useMutation({
    mutationFn: (b:object) => apiClient.post("/recruitment/jobs", b),
    onSuccess: () => { toast.success("Job posted!"); void qc.invalidateQueries({queryKey:["jobs"]}); setShowJobForm(false); }
  });

  const jobs = jobsData?.items ?? [];
  const applicants = appsData?.items ?? [];
  const inp = "w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]";

  const jobCols: ColumnDef<any,unknown>[] = [
    { header:"Job Title", accessorKey:"title", cell:({row})=><div><p className="font-medium text-sm">{row.original.title}</p><p className="text-xs text-[hsl(var(--foreground-muted))] capitalize">{row.original.employment_type?.replace("_"," ")}</p></div> },
    { header:"Status", accessorKey:"status", cell:({getValue})=>{ const s=getValue<string>(); const cfg=jobStatusConfig[s]??{label:s,variant:"default" as const}; return <Badge variant={cfg.variant}>{cfg.label}</Badge>; }},
    { header:"Location", accessorKey:"location", cell:({row})=><span className="text-sm text-[hsl(var(--foreground-subtle))]">{row.original.is_remote?"Remote":row.original.location||"—"}</span> },
    { header:"Openings", accessorKey:"openings", cell:({getValue})=><span className="font-mono text-sm">{getValue<number>()}</span> },
    { header:"Deadline", accessorKey:"deadline", cell:({getValue})=>{ const v=getValue<string|null>(); return <span className="text-sm text-[hsl(var(--foreground-subtle))]">{v?new Date(v).toLocaleDateString("en-US",{day:"numeric",month:"short",year:"numeric"}):"No deadline"}</span>; }},
  ];

  const appCols: ColumnDef<any,unknown>[] = [
    { header:"Applicant", accessorKey:"full_name", cell:({row})=><div><p className="font-medium text-sm">{row.original.full_name}</p><p className="text-xs text-[hsl(var(--foreground-muted))]">{row.original.email}</p></div> },
    { header:"Stage", accessorKey:"current_stage", cell:({getValue})=><span className="text-sm">{getValue<string>()}</span> },
    { header:"Status", accessorKey:"status", cell:({getValue})=>{ const s=getValue<string>(); const cfg=appStatusConfig[s]??{label:s,variant:"default" as const}; return <Badge variant={cfg.variant}>{cfg.label}</Badge>; }},
    { header:"Experience", accessorKey:"experience_years", cell:({getValue})=>{ const v=getValue<number|null>(); return <span className="text-sm text-[hsl(var(--foreground-subtle))]">{v?`${v} yrs`:"—"}</span>; }},
    { header:"Applied", accessorKey:"created_at", cell:({getValue})=><span className="text-xs text-[hsl(var(--foreground-muted))]">{new Date(getValue<string>()).toLocaleDateString()}</span> },
  ];

  return (
    <div className="space-y-6">
      <PageHeader title="Recruitment" description="Manage job postings and applicant pipeline."
        action={<Button icon={<Plus size={15}/>} onClick={()=>setShowJobForm(true)}>Post Job</Button>}/>
      <div className="grid grid-cols-4 gap-4">
        <Card><div className="flex items-center gap-3"><div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[hsl(var(--success-subtle))]"><Briefcase size={16} className="text-[hsl(var(--success))]"/></div><div><p className="text-xl font-semibold font-heading">{jobs.filter((j:any)=>j.status==="open").length}</p><p className="text-xs text-[hsl(var(--foreground-muted))]">Open Jobs</p></div></div></Card>
        <Card><div className="flex items-center gap-3"><div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[hsl(var(--info-subtle))]"><Users size={16} className="text-[hsl(var(--info))]"/></div><div><p className="text-xl font-semibold font-heading">{applicants.length}</p><p className="text-xs text-[hsl(var(--foreground-muted))]">Total Applicants</p></div></div></Card>
        <Card><div className="flex items-center gap-3"><div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[hsl(var(--warning-subtle))]"><Clock size={16} className="text-[hsl(var(--warning))]"/></div><div><p className="text-xl font-semibold font-heading">{applicants.filter((a:any)=>a.status==="interview").length}</p><p className="text-xs text-[hsl(var(--foreground-muted))]">In Interview</p></div></div></Card>
        <Card><div className="flex items-center gap-3"><div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[hsl(var(--success-subtle))]"><CheckCircle size={16} className="text-[hsl(var(--success))]"/></div><div><p className="text-xl font-semibold font-heading">{applicants.filter((a:any)=>a.status==="hired").length}</p><p className="text-xs text-[hsl(var(--foreground-muted))]">Hired</p></div></div></Card>
      </div>
      {showJobForm && (
        <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-5 space-y-4">
          <h3 className="font-heading text-sm font-semibold">Post New Job</h3>
          <div className="grid grid-cols-2 gap-4">
            <div><label className="block text-xs font-medium mb-1">Job Title *</label><input value={jobForm.title} onChange={e=>setJobForm(f=>({...f,title:e.target.value}))} placeholder="Senior Engineer" className={inp}/></div>
            <div><label className="block text-xs font-medium mb-1">Employment Type</label><select value={jobForm.employment_type} onChange={e=>setJobForm(f=>({...f,employment_type:e.target.value}))} className={inp}><option value="full_time">Full Time</option><option value="part_time">Part Time</option><option value="contract">Contract</option><option value="intern">Intern</option></select></div>
            <div><label className="block text-xs font-medium mb-1">Location</label><input value={jobForm.location} onChange={e=>setJobForm(f=>({...f,location:e.target.value}))} placeholder="Karachi, Pakistan" className={inp}/></div>
            <div><label className="block text-xs font-medium mb-1">Openings</label><input type="number" value={jobForm.openings} onChange={e=>setJobForm(f=>({...f,openings:parseInt(e.target.value)}))} min={1} className={inp}/></div>
            <div><label className="block text-xs font-medium mb-1">Min Salary</label><input type="number" value={jobForm.salary_min} onChange={e=>setJobForm(f=>({...f,salary_min:e.target.value}))} placeholder="50000" className={inp}/></div>
            <div><label className="block text-xs font-medium mb-1">Max Salary</label><input type="number" value={jobForm.salary_max} onChange={e=>setJobForm(f=>({...f,salary_max:e.target.value}))} placeholder="80000" className={inp}/></div>
          </div>
          <div className="flex items-center gap-2"><input type="checkbox" id="remote" checked={jobForm.is_remote} onChange={e=>setJobForm(f=>({...f,is_remote:e.target.checked}))}/><label htmlFor="remote" className="text-sm">Remote Position</label></div>
          <div className="flex justify-end gap-2">
            <Button variant="outline" size="sm" onClick={()=>setShowJobForm(false)}>Cancel</Button>
            <Button size="sm" disabled={!jobForm.title||createJob.isPending} onClick={()=>createJob.mutate({...jobForm,salary_min:jobForm.salary_min||undefined,salary_max:jobForm.salary_max||undefined})}>{createJob.isPending?"Posting...":"Post Job"}</Button>
          </div>
        </div>
      )}
      <div className="flex gap-1 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--background-subtle))] p-1 w-fit">
        {(["jobs","applicants"] as const).map(t=>(
          <button key={t} onClick={()=>setTab(t)} className={"rounded-md px-4 py-1.5 text-sm font-medium transition-colors capitalize "+(tab===t?"bg-[hsl(var(--background))] shadow-sm text-[hsl(var(--foreground))]":"text-[hsl(var(--foreground-muted))] hover:text-[hsl(var(--foreground))]")}>{t}</button>
        ))}
      </div>
      {tab==="jobs" ? (
        <DataTable data={jobs} columns={jobCols} isLoading={jobsLoading} searchPlaceholder="Search jobs..." emptyState={<EmptyState icon={Briefcase} title="No jobs posted" description="Post your first job opening." action={<Button icon={<Plus size={14}/>} onClick={()=>setShowJobForm(true)}>Post Job</Button>}/>}/>
      ) : (
        <DataTable data={applicants} columns={appCols} isLoading={appsLoading} searchPlaceholder="Search applicants..." emptyState={<EmptyState icon={UserSearch} title="No applicants yet" description="Applicants will appear here once they apply."/>}/>
      )}
    </div>
  );
}