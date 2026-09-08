"use client";
import { useState } from "react";
import { Clock, Plus, Trash2, Moon, Sun } from "lucide-react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import apiClient from "@/services/api-client";
import { Badge, Button, Card, EmptyState, PageHeader } from "@/components/atoms";
import { cn } from "@/utils/cn";

const DAYS = ["mon","tue","wed","thu","fri","sat","sun"];
const DAY_LABELS: Record<string,string> = { mon:"M",tue:"T",wed:"W",thu:"T",fri:"F",sat:"S",sun:"S" };

export default function ShiftsPage() {
  const qc = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ name:"", code:"", start_time:"09:00", end_time:"18:00", color:"#3b82f6", late_grace_minutes:10, break_duration_minutes:60, work_days:["mon","tue","wed","thu","fri"], is_overnight:false });

  const { data, isLoading } = useQuery({ queryKey:["shifts"], queryFn: async () => { const {data} = await apiClient.get("/shifts"); return data; }});
  const create = useMutation({
    mutationFn: (b:any) => apiClient.post("/shifts", { name:b.name, code:b.code, start_time:b.start_time, end_time:b.end_time, is_overnight:b.is_overnight, late_grace_minutes:b.late_grace_minutes, break_duration_minutes:b.break_duration_minutes, color:b.color, work_days:b.work_days }),
    onSuccess: () => { toast.success("Shift created"); void qc.invalidateQueries({queryKey:["shifts"]}); setShowForm(false); }
  });
  const remove = useMutation({ mutationFn: (id:string) => apiClient.delete(`/shifts/${id}`), onSuccess: () => { toast.success("Deleted"); void qc.invalidateQueries({queryKey:["shifts"]}); }});

  const toggleDay = (day:string) => setForm(f => ({ ...f, work_days: f.work_days.includes(day) ? f.work_days.filter(d=>d!==day) : [...f.work_days,day] }));
  const inp = "w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]";
  const shifts = data?.items ?? [];

  function calcHours(start: string, end: string, overnight: boolean) {
    const [sh, sm] = start.split(":").map(Number);
    const [eh, em] = end.split(":").map(Number);
    let mins = (eh ?? 0) * 60 + (em ?? 0) - ((sh ?? 0) * 60 + (sm ?? 0));
    if (overnight) mins += 24 * 60;
    return (mins / 60).toFixed(1);
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Shifts" description="Define work shifts and schedules." action={<Button icon={<Plus size={15}/>} onClick={()=>setShowForm(true)}>New Shift</Button>}/>
      {showForm && (
        <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-5 space-y-4">
          <h3 className="font-heading text-sm font-semibold">New Shift</h3>
          <div className="grid grid-cols-4 gap-4">
            <div className="col-span-2"><label className="block text-xs font-medium mb-1">Shift Name *</label><input value={form.name} onChange={e=>setForm(f=>({...f,name:e.target.value}))} placeholder="Morning Shift" className={inp}/></div>
            <div><label className="block text-xs font-medium mb-1">Code</label><input value={form.code} onChange={e=>setForm(f=>({...f,code:e.target.value.toUpperCase()}))} placeholder="MRN" className={inp}/></div>
            <div><label className="block text-xs font-medium mb-1">Color</label><input type="color" value={form.color} onChange={e=>setForm(f=>({...f,color:e.target.value}))} className="h-9 w-full rounded-md border border-[hsl(var(--border))] px-1"/></div>
            <div><label className="block text-xs font-medium mb-1">Start Time</label><input type="time" value={form.start_time} onChange={e=>setForm(f=>({...f,start_time:e.target.value}))} className={inp}/></div>
            <div><label className="block text-xs font-medium mb-1">End Time</label><input type="time" value={form.end_time} onChange={e=>setForm(f=>({...f,end_time:e.target.value}))} className={inp}/></div>
            <div><label className="block text-xs font-medium mb-1">Late Grace (min)</label><input type="number" value={form.late_grace_minutes} onChange={e=>setForm(f=>({...f,late_grace_minutes:parseInt(e.target.value)}))} className={inp}/></div>
            <div><label className="block text-xs font-medium mb-1">Break (min)</label><input type="number" value={form.break_duration_minutes} onChange={e=>setForm(f=>({...f,break_duration_minutes:parseInt(e.target.value)}))} className={inp}/></div>
          </div>
          <div>
            <label className="block text-xs font-medium mb-2">Working Days</label>
            <div className="flex gap-1.5">
              {DAYS.map(day=>(
                <button key={day} onClick={()=>toggleDay(day)} className={cn("h-8 w-8 rounded-full text-xs font-semibold transition-colors", form.work_days.includes(day)?"bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]":"bg-[hsl(var(--secondary))] text-[hsl(var(--foreground-muted))] hover:bg-[hsl(var(--secondary-hover))]")}>
                  {DAY_LABELS[day]}
                </button>
              ))}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <input type="checkbox" id="overnight" checked={form.is_overnight} onChange={e=>setForm(f=>({...f,is_overnight:e.target.checked}))}/>
            <label htmlFor="overnight" className="text-sm">Overnight shift (crosses midnight)</label>
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="outline" size="sm" onClick={()=>setShowForm(false)}>Cancel</Button>
            <Button size="sm" disabled={!form.name||!form.code||create.isPending} onClick={()=>create.mutate(form)}>{create.isPending?"Creating...":"Create Shift"}</Button>
          </div>
        </div>
      )}
      {isLoading ? <div className="grid grid-cols-3 gap-4">{Array.from({length:3}).map((_,i)=><div key={i} className="h-40 rounded-xl bg-[hsl(var(--secondary))] animate-pulse"/>)}</div>
      : shifts.length===0 ? <EmptyState icon={Clock} title="No shifts defined" description="Create work shifts to manage attendance schedules." action={<Button icon={<Plus size={14}/>} onClick={()=>setShowForm(true)}>Create Shift</Button>}/>
      : <div className="grid grid-cols-3 gap-4">{shifts.map((s:any)=>(
        <div key={s.id} className="group relative rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-5 shadow-sm hover:border-[hsl(var(--border-strong))] transition-colors">
          <button onClick={()=>{if(confirm(`Delete "${s.name}"?`))remove.mutate(s.id);}} className="absolute right-3 top-3 opacity-0 group-hover:opacity-100 flex h-6 w-6 items-center justify-center rounded hover:bg-[hsl(var(--status-error-bg))] text-[hsl(var(--destructive))]"><Trash2 size={12}/></button>
          <div className="flex items-center gap-2 mb-3">
            <div className="h-3 w-3 rounded-full" style={{backgroundColor:s.color}}/>
            <div>
              <p className="font-semibold text-sm">{s.name}</p>
              <p className="font-mono text-xs text-[hsl(var(--foreground-muted))]">{s.code}</p>
            </div>
            {s.is_overnight&&<Moon size={13} className="text-[hsl(var(--info))] ml-auto"/>}
          </div>
          <div className="flex items-center gap-2 mb-3">
            <Clock size={13} className="text-[hsl(var(--foreground-muted))]"/>
            <span className="text-sm font-medium">{s.start_time.slice(0,5)} — {s.end_time.slice(0,5)}</span>
            <span className="text-xs text-[hsl(var(--foreground-muted))]">({calcHours(s.start_time.slice(0,5),s.end_time.slice(0,5),s.is_overnight)}h)</span>
          </div>
          <div className="flex gap-1">
            {DAYS.map(day=>(
              <span key={day} className={cn("h-6 w-6 rounded-full flex items-center justify-center text-[10px] font-semibold", (s.work_days||[]).includes(day)?"text-white":"bg-[hsl(var(--secondary))] text-[hsl(var(--foreground-muted))]")} style={(s.work_days||[]).includes(day)?{backgroundColor:s.color}:{}}>
                {DAY_LABELS[day]}
              </span>
            ))}
          </div>
          <div className="mt-3 flex gap-3 text-xs text-[hsl(var(--foreground-muted))]">
            <span>Grace: {s.late_grace_minutes}m</span>
            <span>Break: {s.break_duration_minutes}m</span>
          </div>
        </div>
      ))}</div>}
    </div>
  );
}