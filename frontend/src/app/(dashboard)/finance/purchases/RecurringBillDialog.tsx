"use client";

import { useState } from "react";
import { Button } from "@/components/atoms";
import { useCreateRecurringBill, useVendors, type BillLine } from "@/services/finance-purchases.service";
import { FREQ_LABEL, type Frequency } from "@/services/finance-sales.service";
import { inp, Modal } from "../sales/CustomerDialog";
import { blankLine, LinesEditor, linesValid, toPayloadLines } from "./LinesEditor";

const today = () => new Date().toISOString().slice(0, 10);

export function RecurringBillDialog({ baseCurrency, onClose }: { baseCurrency: string; onClose: () => void }) {
  const vendors = useVendors();
  const create = useCreateRecurringBill();
  const [title, setTitle] = useState("");
  const [vendorId, setVendorId] = useState("");
  const [frequency, setFrequency] = useState<Frequency>("monthly");
  const [start, setStart] = useState(today());
  const [end, setEnd] = useState("");
  const [autoPost, setAutoPost] = useState(false);
  const [lines, setLines] = useState<BillLine[]>([blankLine()]);
  const cur = (vendors.data?.find((v) => v.id === vendorId)?.currency ?? baseCurrency).toUpperCase();
  const ready = title.trim().length > 0 && !!vendorId && !!start && linesValid(lines) && (!end || end >= start);

  async function save() {
    await create.mutateAsync({
      title: title.trim(), vendor_id: vendorId, frequency, start_date: start, end_date: end || undefined, auto_post: autoPost,
      lines: toPayloadLines(lines),
    });
    onClose();
  }

  return (
    <Modal title="New recurring bill" onClose={onClose} footer={
      <>
        <Button variant="outline" size="sm" onClick={onClose}>Cancel</Button>
        <Button size="sm" disabled={!ready || create.isPending} onClick={() => void save()}>{create.isPending ? "Saving…" : "Save schedule"}</Button>
      </>
    }>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="sm:col-span-2"><label htmlFor="rb-title" className="mb-1 block text-xs font-medium">Title</label><input id="rb-title" className={inp} placeholder="e.g. Office rent" value={title} onChange={(e) => setTitle(e.target.value)} /></div>
        <div>
          <label htmlFor="rb-vendor" className="mb-1 block text-xs font-medium">Vendor</label>
          <select id="rb-vendor" className={inp} value={vendorId} onChange={(e) => setVendorId(e.target.value)}>
            <option value="">Select…</option>
            {vendors.data?.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
          </select>
        </div>
        <div>
          <label htmlFor="rb-freq" className="mb-1 block text-xs font-medium">Repeats</label>
          <select id="rb-freq" className={inp} value={frequency} onChange={(e) => setFrequency(e.target.value as Frequency)}>
            {(Object.keys(FREQ_LABEL) as Frequency[]).map((f) => <option key={f} value={f}>{FREQ_LABEL[f]}</option>)}
          </select>
        </div>
        <div><label htmlFor="rb-start" className="mb-1 block text-xs font-medium">First bill on</label><input id="rb-start" type="date" className={inp} value={start} onChange={(e) => setStart(e.target.value)} /></div>
        <div><label htmlFor="rb-end" className="mb-1 block text-xs font-medium">Stop after (optional)</label><input id="rb-end" type="date" className={inp} value={end} onChange={(e) => setEnd(e.target.value)} /></div>
      </div>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={autoPost} onChange={(e) => setAutoPost(e.target.checked)} />
        Post automatically to the books. Otherwise each bill is created as a draft for you to review. Bills above the approval limit always wait for approval.
      </label>
      <LinesEditor lines={lines} setLines={setLines} currency={cur} />
    </Modal>
  );
}
