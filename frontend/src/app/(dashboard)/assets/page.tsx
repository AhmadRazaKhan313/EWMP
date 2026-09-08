"use client";
import { useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { Package, Plus, Tag, AlertTriangle, CheckCircle, Settings2 } from "lucide-react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import apiClient from "@/services/api-client";
import { DataTable } from "@/components/molecules/DataTable";
import { Badge, Button, Card, EmptyState, PageHeader } from "@/components/atoms";
import { AssetDrawer } from "@/components/organisms/AssetDrawer";

const statusConfig: Record<string,{label:string;variant:"success"|"warning"|"error"|"default"|"info"}> = {
  available:    {label:"Available",    variant:"success"},
  assigned:     {label:"Assigned",     variant:"info"},
  under_repair: {label:"Under Repair", variant:"warning"},
  disposed:     {label:"Disposed",     variant:"error"},
  lost:         {label:"Lost",         variant:"error"},
};

const CATEGORIES = ["Laptop","Desktop","Monitor","Keyboard","Mouse","Headset","Phone","Tablet","Chair","Desk","Server","Networking","Printer","Camera","Other"];

export default function AssetsPage() {
  const qc = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [selectedAsset, setSelectedAsset] = useState<any | null>(null);
  const [form, setForm] = useState({ name:"", asset_tag:"", category:"Laptop", brand:"", model:"", serial_number:"", purchase_cost:"", purchase_date:"", warranty_expiry:"", location:"" });

  const { data, isLoading } = useQuery({ queryKey:["assets"], queryFn: async () => { const {data} = await apiClient.get("/assets"); return data; }});
  const create = useMutation({ mutationFn: (b:object) => apiClient.post("/assets", b), onSuccess: () => { toast.success("Asset created"); void qc.invalidateQueries({queryKey:["assets"]}); setShowForm(false); setForm({name:"",asset_tag:"",category:"Laptop",brand:"",model:"",serial_number:"",purchase_cost:"",purchase_date:"",warranty_expiry:"",location:""}); }, onError: ()=>toast.error("Failed to create asset") });

  const inp = "w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]";
  const assets = data?.items ?? [];
  const available = assets.filter((a:any)=>a.status==="available").length;
  const assigned = assets.filter((a:any)=>a.status==="assigned").length;
  const repair = assets.filter((a:any)=>a.status==="under_repair").length;

  const columns: ColumnDef<any,unknown>[] = [
    { header:"Asset", accessorKey:"name", cell:({row})=>(
      <div className="flex items-center gap-3">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[hsl(var(--secondary))]"><Package size={15} className="text-[hsl(var(--foreground-subtle))]"/></div>
        <div><p className="font-medium text-sm">{row.original.name}</p><p className="font-mono text-[11px] text-[hsl(var(--foreground-muted))]">{row.original.asset_tag}</p></div>
      </div>
    ), size:220 },
    { header:"Category", accessorKey:"category", cell:({getValue})=><span className="text-sm text-[hsl(var(--foreground-subtle))]">{getValue<string>()}</span> },
    { header:"Brand / Model", accessorKey:"brand", cell:({row})=><span className="text-sm text-[hsl(var(--foreground-subtle))]">{[row.original.brand,row.original.model].filter(Boolean).join(" ") || "—"}</span> },
    { header:"Serial No.", accessorKey:"serial_number", cell:({getValue})=><span className="font-mono text-xs text-[hsl(var(--foreground-subtle))]">{getValue<string|null>()||"—"}</span> },
    { header:"Status", accessorKey:"status", cell:({getValue})=>{ const s=getValue<string>(); const cfg=statusConfig[s]??{label:s,variant:"default" as const}; return <Badge variant={cfg.variant}>{cfg.label}</Badge>; }},
    { header:"Location", accessorKey:"location", cell:({getValue})=><span className="text-sm text-[hsl(var(--foreground-subtle))]">{getValue<string|null>()||"—"}</span> },
    { header:"Warranty", accessorKey:"warranty_expiry", cell:({getValue})=>{ const v=getValue<string|null>(); if(!v) return <span className="text-[hsl(var(--foreground-muted))]">—</span>; const expired=new Date(v)<new Date(); return <span className={"text-sm "+(expired?"text-[hsl(var(--destructive))]":"text-[hsl(var(--foreground-subtle))]")}>{new Date(v).toLocaleDateString("en-US",{day:"numeric",month:"short",year:"numeric"})}</span>; }},
    { header:"", id:"actions", cell:({row})=>(
      <button
        onClick={()=>setSelectedAsset(row.original)}
        className="flex items-center gap-1.5 rounded-md border border-[hsl(var(--border))] px-2.5 py-1 text-xs text-[hsl(var(--foreground-subtle))] hover:border-[hsl(var(--primary))] hover:text-[hsl(var(--primary))]"
      >
        <Settings2 size={12}/> Manage
      </button>
    ), size:100 },
  ];

  return (
    <div className="space-y-6">
      <PageHeader title="Asset Management" description="Track and manage IT assets, equipment, and accessories." action={<Button icon={<Plus size={15}/>} onClick={()=>setShowForm(true)}>Add Asset</Button>}/>
      <div className="grid grid-cols-4 gap-4">
        <Card><div className="flex items-center gap-3"><div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[hsl(var(--secondary))]"><Package size={16}/></div><div><p className="text-2xl font-semibold font-heading">{assets.length}</p><p className="text-xs text-[hsl(var(--foreground-muted))]">Total Assets</p></div></div></Card>
        <Card><div className="flex items-center gap-3"><div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[hsl(var(--success-subtle))]"><CheckCircle size={16} className="text-[hsl(var(--success))]"/></div><div><p className="text-2xl font-semibold font-heading">{available}</p><p className="text-xs text-[hsl(var(--foreground-muted))]">Available</p></div></div></Card>
        <Card><div className="flex items-center gap-3"><div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[hsl(var(--info-subtle))]"><Tag size={16} className="text-[hsl(var(--info))]"/></div><div><p className="text-2xl font-semibold font-heading">{assigned}</p><p className="text-xs text-[hsl(var(--foreground-muted))]">Assigned</p></div></div></Card>
        <Card><div className="flex items-center gap-3"><div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[hsl(var(--warning-subtle))]"><AlertTriangle size={16} className="text-[hsl(var(--warning))]"/></div><div><p className="text-2xl font-semibold font-heading">{repair}</p><p className="text-xs text-[hsl(var(--foreground-muted))]">Under Repair</p></div></div></Card>
      </div>
      {showForm && (
        <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-5 space-y-4">
          <h3 className="font-heading text-sm font-semibold">Add New Asset</h3>
          <div className="grid grid-cols-3 gap-4">
            <div className="col-span-2"><label className="block text-xs font-medium mb-1">Asset Name *</label><input value={form.name} onChange={e=>setForm(f=>({...f,name:e.target.value}))} placeholder="MacBook Pro 14-inch" className={inp}/></div>
            <div><label className="block text-xs font-medium mb-1">Asset Tag *</label><input value={form.asset_tag} onChange={e=>setForm(f=>({...f,asset_tag:e.target.value.toUpperCase()}))} placeholder="ASSET-001" className={inp}/></div>
            <div><label className="block text-xs font-medium mb-1">Category</label><select value={form.category} onChange={e=>setForm(f=>({...f,category:e.target.value}))} className={inp}>{CATEGORIES.map(c=><option key={c} value={c}>{c}</option>)}</select></div>
            <div><label className="block text-xs font-medium mb-1">Brand</label><input value={form.brand} onChange={e=>setForm(f=>({...f,brand:e.target.value}))} placeholder="Apple" className={inp}/></div>
            <div><label className="block text-xs font-medium mb-1">Model</label><input value={form.model} onChange={e=>setForm(f=>({...f,model:e.target.value}))} placeholder="MacBook Pro M3" className={inp}/></div>
            <div><label className="block text-xs font-medium mb-1">Serial Number</label><input value={form.serial_number} onChange={e=>setForm(f=>({...f,serial_number:e.target.value}))} placeholder="SN123456" className={inp}/></div>
            <div><label className="block text-xs font-medium mb-1">Purchase Cost</label><input type="number" value={form.purchase_cost} onChange={e=>setForm(f=>({...f,purchase_cost:e.target.value}))} placeholder="1299.00" className={inp}/></div>
            <div><label className="block text-xs font-medium mb-1">Purchase Date</label><input type="date" value={form.purchase_date} onChange={e=>setForm(f=>({...f,purchase_date:e.target.value}))} className={inp}/></div>
            <div><label className="block text-xs font-medium mb-1">Warranty Expiry</label><input type="date" value={form.warranty_expiry} onChange={e=>setForm(f=>({...f,warranty_expiry:e.target.value}))} className={inp}/></div>
            <div><label className="block text-xs font-medium mb-1">Location</label><input value={form.location} onChange={e=>setForm(f=>({...f,location:e.target.value}))} placeholder="Karachi Office" className={inp}/></div>
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="outline" size="sm" onClick={()=>setShowForm(false)}>Cancel</Button>
            <Button size="sm" disabled={!form.name||!form.asset_tag||create.isPending} onClick={()=>create.mutate(form)}>{create.isPending?"Saving...":"Add Asset"}</Button>
          </div>
        </div>
      )}
      <DataTable data={assets} columns={columns} isLoading={isLoading} searchPlaceholder="Search by name, tag, serial..." emptyState={<EmptyState icon={Package} title="No assets yet" description="Start tracking your IT assets and equipment." action={<Button icon={<Plus size={14}/>} onClick={()=>setShowForm(true)}>Add First Asset</Button>}/>}/>
      {selectedAsset && <AssetDrawer asset={selectedAsset} onClose={()=>setSelectedAsset(null)} />}
    </div>
  );
}