"use client";

import { useState } from "react";
import { Button } from "@/components/atoms";
import { useCreateVendor } from "@/services/finance-purchases.service";
import { inp, Modal } from "../sales/CustomerDialog";

export function VendorDialog({ onClose, onCreated }: { onClose: () => void; onCreated?: (id: string) => void }) {
  const create = useCreateVendor();
  const [f, setF] = useState({ name: "", company: "", email: "", phone: "", currency: "", terms: "0" });
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value });
  const ready = f.name.trim().length > 0 && (f.currency === "" || /^[A-Za-z]{3}$/.test(f.currency)) && /^\d+$/.test(f.terms);

  async function save() {
    const v = await create.mutateAsync({
      name: f.name.trim(), company: f.company.trim() || null, email: f.email.trim() || null, phone: f.phone.trim() || null,
      currency: f.currency ? f.currency.toUpperCase() : null, payment_terms_days: parseInt(f.terms, 10),
    });
    onCreated?.(v.id);
    onClose();
  }

  return (
    <Modal title="Add vendor" onClose={onClose} footer={
      <>
        <Button variant="outline" size="sm" onClick={onClose}>Cancel</Button>
        <Button size="sm" disabled={!ready || create.isPending} onClick={() => void save()}>{create.isPending ? "Saving…" : "Save vendor"}</Button>
      </>
    }>
      <div className="grid gap-3 sm:grid-cols-2">
        <div><label htmlFor="v-name" className="mb-1 block text-xs font-medium">Name</label><input id="v-name" className={inp} value={f.name} onChange={set("name")} /></div>
        <div><label htmlFor="v-company" className="mb-1 block text-xs font-medium">Company</label><input id="v-company" className={inp} value={f.company} onChange={set("company")} /></div>
        <div><label htmlFor="v-email" className="mb-1 block text-xs font-medium">Email</label><input id="v-email" type="email" className={inp} value={f.email} onChange={set("email")} /></div>
        <div><label htmlFor="v-phone" className="mb-1 block text-xs font-medium">Phone</label><input id="v-phone" className={inp} value={f.phone} onChange={set("phone")} /></div>
        <div><label htmlFor="v-cur" className="mb-1 block text-xs font-medium">Currency (blank = base)</label><input id="v-cur" maxLength={3} placeholder="USD" className={inp} value={f.currency} onChange={set("currency")} /></div>
        <div><label htmlFor="v-terms" className="mb-1 block text-xs font-medium">Payment terms (days)</label><input id="v-terms" inputMode="numeric" className={inp} value={f.terms} onChange={set("terms")} /></div>
      </div>
    </Modal>
  );
}
