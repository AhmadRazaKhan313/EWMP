"use client";
import { useState } from "react";
import { Plane, Plus, Edit, Trash2, Check, X } from "lucide-react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import apiClient from "@/services/api-client";
import { Badge, Button, EmptyState, PageHeader } from "@/components/atoms";

export default function LeaveTypesPage() {
  const qc = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ name:"", code:"", days_per_year:"0", is_paid:true, requires_approval:true, requires_document:false, is_carry_forward:false, color:"#3b82f6" });

  const { data, isLoading } = useQuery({ queryKey:["leave-types"], queryFn: async () => { const {data} = await apiClient.get("/leave/types"); return data; }});
  const create = useMutation({ mutationFn: (b:any) => apiClient.post("/leave/types", b), onSuccess: () => { toast.success("Leave type created"); void qc.invalidateQueries({queryKey:["leave-types"]}); setShowForm(false); }});
  const update = useMutation({ mutationFn: ({id,b}:{id:string;b:object}) => apiClient.patch(`/leave/types/${id}`, b), onSuccess: () => { toast.success("Updated"); void qc.invalidateQueries({queryKey:["leave-types"]}); }});

  const inp = "w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]";
  const types = data?.items ?? [];

  const BoolIcon = ({ val }: { val: boolean }) => val ? <Check size={13} className="text-[hsl(var(--success))]"/> : <X size={13} className="text-[hsl(var(--foreground-muted))]"/>;

  return (
    <div className="space-y-6">
      <PageHeader title="Leave Types" description="Configure leave categories and accrual policies." action={<Button icon={<Plus size={15}/>} onClick={()=>setShowForm(true)}>New Leave Type</Button>}/>
      {showForm && (
        <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-5 space-y-4">
          <h3 className="font-heading text-sm font-semibold">New Leave Type</h3>
          <div className="grid grid-cols-4 gap-4">
            <div className="col-span-2"><label className="block text-xs font-medium mb-1">Name *</label><input value={form.name} onChange={e=>setForm(f=>({...f,name:e.target.value}))} placeholder="Annual Leave" className={inp}/></div>
            <div><label className="block text-xs font-medium mb-1">Code</label><input value={form.code} onChange={e=>setForm(f=>({...f,code:e.target.value.toUpperCase()}))} placeholder="AL" className={inp}/></div>
            <div><label className="block text-xs font-medium mb-1">Days/Year</label><input type="number" value={form.days_per_year} onChange={e=>setForm(f=>({...f,days_per_year:e.target.value}))} className={inp}/></div>
          </div>
          <div><label className="block text-xs font-medium mb-1">Color</label><input type="color" value={form.color} onChange={e=>setForm(f=>({...f,color:e.target.value}))} className="h-9 w-24 rounded-md border border-[hsl(var(--border))] px-1"/></div>
          <div className="grid grid-cols-2 gap-3">
            {[
              {key:"is_paid",label:"Paid Leave"},
              {key:"requires_approval",label:"Requires Approval"},
              {key:"requires_document",label:"Requires Document"},
              {key:"is_carry_forward",label:"Carry Forward"},
            ].map(opt=>(
              <label key={opt.key} className="flex items-center gap-2 cursor-pointer">
                <input type="checkbox" checked={form[opt.key as keyof typeof form] as boolean} onChange={e=>setForm(f=>({...f,[opt.key]:e.target.checked}))} className="rounded"/>
                <span className="text-sm">{opt.label}</span>
              </label>
            ))}
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="outline" size="sm" onClick={()=>setShowForm(false)}>Cancel</Button>
            <Button size="sm" disabled={!form.name||!form.code||create.isPending} onClick={()=>create.mutate(form)}>{create.isPending?"Saving...":"Create"}</Button>
          </div>
        </div>
      )}
      {isLoading ? <div className="space-y-2">{Array.from({length:5}).map((_,i)=><div key={i} className="h-16 rounded-xl bg-[hsl(var(--secondary))] animate-pulse"/>)}</div>
      : types.length===0 ? <EmptyState icon={Plane} title="No leave types" description="Create leave types like Annual, Sick, Maternity leave." action={<Button icon={<Plus size={14}/>} onClick={()=>setShowForm(true)}>Create Leave Type</Button>}/>
      : (
        <div className="overflow-hidden rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] shadow-sm">
          <table className="w-full text-sm">
            <thead><tr className="border-b border-[hsl(var(--border))] bg-[hsl(var(--background-subtle))]">
              {["Leave Type","Code","Days/Year","Paid","Approval","Document","Carry Fwd","Status"].map(h=>(
                <th key={h} className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-[hsl(var(--foreground-muted))]">{h}</th>
              ))}
            </tr></thead>
            <tbody className="divide-y divide-[hsl(var(--border))]">
              {types.map((t:any)=>(
                <tr key={t.id} className="hover:bg-[hsl(var(--background-subtle))] transition-colors">
                  <td className="px-4 py-3"><div className="flex items-center gap-2"><div className="h-3 w-3 rounded-full" style={{backgroundColor:t.color}}/><span className="font-medium">{t.name}</span></div></td>
                  <td className="px-4 py-3"><span className="font-mono text-xs bg-[hsl(var(--secondary))] px-2 py-0.5 rounded">{t.code}</span></td>
                  <td className="px-4 py-3 font-mono font-semibold">{t.days_per_year}</td>
                  <td className="px-4 py-3"><BoolIcon val={t.is_paid}/></td>
                  <td className="px-4 py-3"><BoolIcon val={t.requires_approval}/></td>
                  <td className="px-4 py-3"><BoolIcon val={t.requires_document}/></td>
                  <td className="px-4 py-3"><BoolIcon val={t.is_carry_forward}/></td>
                  <td className="px-4 py-3"><Badge variant={t.is_active?"success":"error"}>{t.is_active?"Active":"Inactive"}</Badge></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}