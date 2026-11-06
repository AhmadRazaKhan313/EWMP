"use client";

import { useState } from "react";
import { Button } from "@/components/atoms";
import { useCreateOrder, useVendors, type BillLine } from "@/services/finance-purchases.service";
import { inp, Modal } from "../sales/CustomerDialog";
import { blankLine, LinesEditor, linesValid, toPayloadLines } from "./LinesEditor";

const today = () => new Date().toISOString().slice(0, 10);

export function OrderDialog({ baseCurrency, onClose }: { baseCurrency: string; onClose: () => void }) {
  const vendors = useVendors();
  const create = useCreateOrder();
  const [vendorId, setVendorId] = useState("");
  const [issue, setIssue] = useState(today());
  const [expected, setExpected] = useState("");
  const [notes, setNotes] = useState("");
  const [lines, setLines] = useState<BillLine[]>([blankLine()]);
  const cur = (vendors.data?.find((v) => v.id === vendorId)?.currency ?? baseCurrency).toUpperCase();
  const ready = !!vendorId && !!issue && linesValid(lines) && (!expected || expected >= issue);

  async function save(send: boolean) {
    await create.mutateAsync({
      vendor_id: vendorId, issue_date: issue, expected_date: expected || undefined, notes: notes.trim() || undefined, send,
      lines: toPayloadLines(lines),
    });
    onClose();
  }

  return (
    <Modal title="New purchase order" onClose={onClose} footer={
      <>
        <Button variant="outline" size="sm" onClick={onClose}>Cancel</Button>
        <Button variant="outline" size="sm" disabled={!ready || create.isPending} onClick={() => void save(false)}>Save as draft</Button>
        <Button size="sm" disabled={!ready || create.isPending} onClick={() => void save(true)}>{create.isPending ? "Saving…" : "Save & mark sent"}</Button>
      </>
    }>
      <div className="grid gap-3 sm:grid-cols-3">
        <div>
          <label htmlFor="po-vendor" className="mb-1 block text-xs font-medium">Vendor</label>
          <select id="po-vendor" className={inp} value={vendorId} onChange={(e) => setVendorId(e.target.value)}>
            <option value="">Select…</option>
            {vendors.data?.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
          </select>
        </div>
        <div><label htmlFor="po-date" className="mb-1 block text-xs font-medium">Order date</label><input id="po-date" type="date" className={inp} value={issue} onChange={(e) => setIssue(e.target.value)} /></div>
        <div><label htmlFor="po-exp" className="mb-1 block text-xs font-medium">Expected on (optional)</label><input id="po-exp" type="date" className={inp} value={expected} onChange={(e) => setExpected(e.target.value)} /></div>
      </div>
      <LinesEditor lines={lines} setLines={setLines} currency={cur} />
      <div><label htmlFor="po-notes" className="mb-1 block text-xs font-medium">Notes</label><textarea id="po-notes" rows={2} className={inp} value={notes} onChange={(e) => setNotes(e.target.value)} /></div>
    </Modal>
  );
}
