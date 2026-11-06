"use client";

import { useState } from "react";
import { Button } from "@/components/atoms";
import { useRejectBill, type Bill } from "@/services/finance-purchases.service";
import { inp, Modal } from "../sales/CustomerDialog";

export function RejectDialog({ bill, onClose }: { bill: Bill; onClose: () => void }) {
  const reject = useRejectBill();
  const [reason, setReason] = useState("");
  async function save() {
    await reject.mutateAsync({ id: bill.id, reason: reason.trim() });
    onClose();
  }
  return (
    <Modal title={`Reject ${bill.number}`} onClose={onClose} footer={
      <>
        <Button variant="outline" size="sm" onClick={onClose}>Cancel</Button>
        <Button size="sm" disabled={!reason.trim() || reject.isPending} onClick={() => void save()}>Reject bill</Button>
      </>
    }>
      <label htmlFor="rej-reason" className="mb-1 block text-xs font-medium">Reason</label>
      <textarea id="rej-reason" rows={3} className={inp} value={reason} onChange={(e) => setReason(e.target.value)} />
    </Modal>
  );
}
