"use client";

import { useState } from "react";
import { X } from "lucide-react";
import { Button } from "@/components/atoms";
import { useCreateCustomer } from "@/services/finance-sales.service";

export const inp =
  "w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-2 text-sm outline-none focus:border-[hsl(var(--brand-300))] focus:ring-4 focus:ring-[hsl(var(--brand-100))]";

export function Modal({ title, onClose, children, footer }: { title: string; onClose: () => void; children: React.ReactNode; footer: React.ReactNode }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose} role="presentation">
      <div role="dialog" aria-modal="true" aria-label={title} onClick={(e) => e.stopPropagation()}
        className="flex max-h-[90vh] w-full max-w-2xl flex-col rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] shadow-xl">
        <div className="flex items-center justify-between border-b border-[hsl(var(--border))] p-4">
          <h2 className="font-heading text-lg font-semibold">{title}</h2>
          <button aria-label="Close" onClick={onClose}><X size={18} /></button>
        </div>
        <div className="space-y-4 overflow-y-auto p-4">{children}</div>
        <div className="flex justify-end gap-2 border-t border-[hsl(var(--border))] p-4">{footer}</div>
      </div>
    </div>
  );
}

export function CustomerDialog({ onClose, onCreated }: { onClose: () => void; onCreated?: (id: string) => void }) {
  const create = useCreateCustomer();
  const [f, setF] = useState({ name: "", company: "", email: "", phone: "", currency: "", terms: "0", remind: false });
  const set = (k: Exclude<keyof typeof f, "remind">) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value });
  const ready = f.name.trim().length > 0 && (f.currency === "" || /^[A-Za-z]{3}$/.test(f.currency)) && /^\d+$/.test(f.terms);

  async function save() {
    const c = await create.mutateAsync({
      name: f.name.trim(), company: f.company.trim() || null, email: f.email.trim() || null, phone: f.phone.trim() || null,
      currency: f.currency ? f.currency.toUpperCase() : null, payment_terms_days: parseInt(f.terms, 10), auto_remind: f.remind,
    });
    onCreated?.(c.id);
    onClose();
  }

  return (
    <Modal title="Add customer" onClose={onClose} footer={
      <>
        <Button variant="outline" size="sm" onClick={onClose}>Cancel</Button>
        <Button size="sm" disabled={!ready || create.isPending} onClick={() => void save()}>{create.isPending ? "Saving…" : "Save customer"}</Button>
      </>
    }>
      <div className="grid gap-3 sm:grid-cols-2">
        <div><label htmlFor="c-name" className="mb-1 block text-xs font-medium">Name</label><input id="c-name" className={inp} value={f.name} onChange={set("name")} /></div>
        <div><label htmlFor="c-company" className="mb-1 block text-xs font-medium">Company</label><input id="c-company" className={inp} value={f.company} onChange={set("company")} /></div>
        <div><label htmlFor="c-email" className="mb-1 block text-xs font-medium">Email</label><input id="c-email" type="email" className={inp} value={f.email} onChange={set("email")} /></div>
        <div><label htmlFor="c-phone" className="mb-1 block text-xs font-medium">Phone</label><input id="c-phone" className={inp} value={f.phone} onChange={set("phone")} /></div>
        <div><label htmlFor="c-cur" className="mb-1 block text-xs font-medium">Currency (blank = base)</label><input id="c-cur" maxLength={3} placeholder="USD" className={inp} value={f.currency} onChange={set("currency")} /></div>
        <div><label htmlFor="c-terms" className="mb-1 block text-xs font-medium">Payment terms (days)</label><input id="c-terms" inputMode="numeric" className={inp} value={f.terms} onChange={set("terms")} /></div>
      </div>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={f.remind} onChange={(e) => setF({ ...f, remind: e.target.checked })} />
        Email payment reminders automatically when an invoice is overdue (needs an email address)
      </label>
    </Modal>
  );
}
