"use client";
import { useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { TrendingUp, Plus, Target, Star, AlertCircle, CheckCircle2 } from "lucide-react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import apiClient from "@/services/api-client";
import { DataTable } from "@/components/molecules/DataTable";
import { Badge, Button, Card, EmptyState, PageHeader } from "@/components/atoms";

const goalStatusConfig: Record<string, {label:string;variant:"success"|"warning"|"error"|"default"|"info"}> = {
  not_started: {label:"Not Started", variant:"default"},
  in_progress: {label:"In Progress", variant:"info"},
  completed:   {label:"Completed",   variant:"success"},
  cancelled:   {label:"Cancelled",   variant:"error"},
  at_risk:     {label:"At Risk",     variant:"warning"},
};

export default function PerformancePage() {
  const qc = useQueryClient();
  const [tab, setTab] = useState<"goals"|"reviews">("goals");
  const [showGoalForm, setShowGoalForm] = useState(false);
  const [goalForm, setGoalForm] = useState({ title:"", category:"", due_date:"", weight:1 });

  const { data: goalsData, isLoading: goalsLoading } = useQuery({ queryKey:["goals"], queryFn: async () => { const {data} = await apiClient.get("/performance/goals"); return data; }});
  const { data: reviewsData, isLoading: reviewsLoading } = useQuery({ queryKey:["reviews"], queryFn: async () => { const {data} = await apiClient.get("/performance/reviews"); return data; }});

  const updateGoal = useMutation({
    mutationFn: ({id, progress}:{id:string;progress:number}) => apiClient.patch(`/performance/goals/${id}`, {progress_percent:progress}),
    onSuccess: () => { toast.success("Progress updated"); void qc.invalidateQueries({queryKey:["goals"]}); }
  });

  const goals = goalsData?.items ?? [];
  const reviews = reviewsData?.items ?? [];
  const inp = "w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]";

  const goalCols: ColumnDef<any,unknown>[] = [
    { header:"Goal", accessorKey:"title", cell:({row})=><div><p className="font-medium text-sm">{row.original.title}</p>{row.original.category&&<p className="text-xs text-[hsl(var(--foreground-muted))]">{row.original.category}</p>}</div>, size:280 },
    { header:"Status", accessorKey:"status", cell:({getValue})=>{ const s=getValue<string>(); const cfg=goalStatusConfig[s]??{label:s,variant:"default" as const}; return <Badge variant={cfg.variant}>{cfg.label}</Badge>; }},
    { header:"Progress", accessorKey:"progress_percent", cell:({getValue,row})=>{ const p=getValue<number>(); return (
      <div className="flex items-center gap-2">
        <div className="h-1.5 w-20 overflow-hidden rounded-full bg-[hsl(var(--secondary))]">
          <div className={"h-full rounded-full "+(p>=100?"bg-[hsl(var(--success))]":p>=50?"bg-[hsl(var(--info))]":"bg-[hsl(var(--warning))]")} style={{width:`${p}%`}}/>
        </div>
        <span className="text-xs font-mono">{p}%</span>
      </div>
    );}},
    { header:"Due Date", accessorKey:"due_date", cell:({getValue})=>{ const v=getValue<string|null>(); return <span className="text-sm text-[hsl(var(--foreground-subtle))]">{v?new Date(v).toLocaleDateString("en-US",{day:"numeric",month:"short",year:"numeric"}):"No deadline"}</span>; }},
  ];

  const reviewCols: ColumnDef<any,unknown>[] = [
    { header:"Period", accessorKey:"review_period", cell:({row})=><div><p className="font-medium text-sm">{row.original.review_period} {row.original.review_year}</p></div> },
    { header:"Status", accessorKey:"status", cell:({getValue})=>{ const s=getValue<string>(); return <Badge variant={s==="completed"?"success":s==="submitted"?"info":"default"}>{s.charAt(0).toUpperCase()+s.slice(1)}</Badge>; }},
    { header:"Rating", accessorKey:"overall_rating", cell:({getValue})=>{ const r=getValue<string|null>(); return r?<div className="flex items-center gap-1"><Star size={13} className="text-[hsl(var(--warning))]"/><span className="text-sm font-medium">{r}/5</span></div>:<span className="text-[hsl(var(--foreground-muted))]">—</span>; }},
    { header:"Date", accessorKey:"created_at", cell:({getValue})=><span className="text-xs text-[hsl(var(--foreground-muted))]">{new Date(getValue<string>()).toLocaleDateString()}</span> },
  ];

  const completedGoals = goals.filter((g:any)=>g.status==="completed").length;
  const avgProgress = goals.length ? Math.round(goals.reduce((s:number,g:any)=>s+g.progress_percent,0)/goals.length) : 0;

  return (
    <div className="space-y-6">
      <PageHeader title="Performance" description="Track goals, OKRs, and performance reviews." action={<Button icon={<Plus size={15}/>} onClick={()=>setShowGoalForm(true)}>Add Goal</Button>}/>
      <div className="grid grid-cols-4 gap-4">
        <Card><div className="flex items-center gap-3"><div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[hsl(var(--info-subtle))]"><Target size={16} className="text-[hsl(var(--info))]"/></div><div><p className="text-xl font-semibold font-heading">{goals.length}</p><p className="text-xs text-[hsl(var(--foreground-muted))]">Total Goals</p></div></div></Card>
        <Card><div className="flex items-center gap-3"><div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[hsl(var(--success-subtle))]"><CheckCircle2 size={16} className="text-[hsl(var(--success))]"/></div><div><p className="text-xl font-semibold font-heading">{completedGoals}</p><p className="text-xs text-[hsl(var(--foreground-muted))]">Completed</p></div></div></Card>
        <Card><div className="flex items-center gap-3"><div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[hsl(var(--warning-subtle))]"><AlertCircle size={16} className="text-[hsl(var(--warning))]"/></div><div><p className="text-xl font-semibold font-heading">{goals.filter((g:any)=>g.status==="at_risk").length}</p><p className="text-xs text-[hsl(var(--foreground-muted))]">At Risk</p></div></div></Card>
        <Card><div className="flex items-center gap-3"><div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[hsl(var(--secondary))]"><TrendingUp size={16}/></div><div><p className="text-xl font-semibold font-heading">{avgProgress}%</p><p className="text-xs text-[hsl(var(--foreground-muted))]">Avg Progress</p></div></div></Card>
      </div>
      {showGoalForm && (
        <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-5 space-y-4">
          <h3 className="font-heading text-sm font-semibold">New Goal</h3>
          <div className="grid grid-cols-2 gap-4">
            <div className="col-span-2"><label className="block text-xs font-medium mb-1">Goal Title *</label><input value={goalForm.title} onChange={e=>setGoalForm(f=>({...f,title:e.target.value}))} placeholder="Increase customer satisfaction score by 20%" className={inp}/></div>
            <div><label className="block text-xs font-medium mb-1">Category</label><select value={goalForm.category} onChange={e=>setGoalForm(f=>({...f,category:e.target.value}))} className={inp}><option value="">Select</option><option value="Performance">Performance</option><option value="Learning">Learning</option><option value="Leadership">Leadership</option><option value="Innovation">Innovation</option></select></div>
            <div><label className="block text-xs font-medium mb-1">Due Date</label><input type="date" value={goalForm.due_date} onChange={e=>setGoalForm(f=>({...f,due_date:e.target.value}))} className={inp}/></div>
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="outline" size="sm" onClick={()=>setShowGoalForm(false)}>Cancel</Button>
            <Button size="sm" disabled={!goalForm.title} onClick={()=>{ toast.info("Goal creation requires employee selection — coming soon"); setShowGoalForm(false); }}>Add Goal</Button>
          </div>
        </div>
      )}
      <div className="flex gap-1 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--background-subtle))] p-1 w-fit">
        {(["goals","reviews"] as const).map(t=>(
          <button key={t} onClick={()=>setTab(t)} className={"rounded-md px-4 py-1.5 text-sm font-medium transition-colors capitalize "+(tab===t?"bg-[hsl(var(--background))] shadow-sm text-[hsl(var(--foreground))]":"text-[hsl(var(--foreground-muted))] hover:text-[hsl(var(--foreground))]")}>{t}</button>
        ))}
      </div>
      {tab==="goals" ? (
        <DataTable data={goals} columns={goalCols} isLoading={goalsLoading} searchPlaceholder="Search goals..." emptyState={<EmptyState icon={Target} title="No goals yet" description="Set goals for your team members." action={<Button icon={<Plus size={14}/>} onClick={()=>setShowGoalForm(true)}>Add Goal</Button>}/>}/>
      ) : (
        <DataTable data={reviews} columns={reviewCols} isLoading={reviewsLoading} searchPlaceholder="Search reviews..." emptyState={<EmptyState icon={Star} title="No reviews yet" description="Performance reviews will appear here."/>}/>
      )}
    </div>
  );
}