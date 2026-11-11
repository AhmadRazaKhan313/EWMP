"use client";

import { useState } from "react";
import { Button, Skeleton } from "@/components/atoms";
import { categoriesFor, formatMoney, isMoneyAccount, type FinAccount } from "@/services/finance.service";
import { useBookLine, useMatchLine, useSuggestions, type BankLine } from "@/services/finance-banking.service";
import { Modal, inp } from "../sales/CustomerDialog";

export function MatchDialog({ line, currency, onClose }: { line: BankLine; currency: string; onClose: () => void }) {
  const sug = useSuggestions(line.id);
  const match = useMatchLine();
  return (
    <Modal title="Match to a ledger entry" onClose={onClose} footer={<Button variant="outline" size="sm" onClick={onClose}>Close</Button>}>
      <p className="text-sm">{line.date} · {line.description ?? "No description"} · <strong>{formatMoney(line.amount, currency)}</strong></p>
      {sug.isLoading ? <Skeleton className="h-16" /> : !sug.data?.length ? (
        <p className="text-sm text-[hsl(var(--foreground-muted))]">No entry with this amount within 10 days. You can book the line as a new entry instead.</p>
      ) : (
        <ul className="divide-y divide-[hsl(var(--border))] rounded-lg border border-[hsl(var(--border))]">
          {sug.data.map((s) => (
            <li key={s.entry_line_id} className="flex items-center justify-between gap-3 p-3 text-sm">
              <div>
                <p className="font-medium">{s.number} · {s.date}</p>
                <p className="text-xs text-[hsl(var(--foreground-muted))]">{s.memo ?? "No description"}{s.payment_tid ? ` · TID ${s.payment_tid}` : ""}</p>
              </div>
              <Button size="sm" disabled={match.isPending}
                onClick={() => match.mutate({ lineId: line.id, entryLineId: s.entry_line_id }, { onSuccess: onClose })}>Match</Button>
            </li>
          ))}
        </ul>
      )}
    </Modal>
  );
}

export function BookDialog({ line, accounts, currency, onClose }: { line: BankLine; accounts: FinAccount[]; currency: string; onClose: () => void }) {
  const inflow = parseFloat(line.amount) > 0;
  const book = useBookLine();
  const [type, setType] = useState<"income" | "expense" | "transfer">(inflow ? "income" : "expense");
  const [categoryId, setCategoryId] = useState("");
  const [otherId, setOtherId] = useState("");
  const [description, setDescription] = useState(line.description ?? "");
  const cats = type === "transfer" ? [] : categoriesFor(accounts, type);
  const others = accounts.filter((a) => isMoneyAccount(a) && a.is_active && a.id !== line.account_id);
  const ready = type === "transfer" ? !!otherId : !!categoryId;

  return (
    <Modal title="Book this line" onClose={onClose} footer={<>
      <Button variant="outline" size="sm" onClick={onClose}>Cancel</Button>
      <Button size="sm" disabled={!ready || book.isPending}
        onClick={() => book.mutate({ lineId: line.id, type, description: description.trim() || undefined,
          ...(type === "transfer" ? { other_account_id: otherId } : { category_id: categoryId }) }, { onSuccess: onClose })}>
        {book.isPending ? "Booking…" : "Book and match"}
      </Button>
    </>}>
      <p className="text-sm">{line.date} · {line.description ?? "No description"} · <strong>{formatMoney(line.amount, currency)}</strong></p>
      <div>
        <label htmlFor="bk-type" className="mb-1 block text-xs font-medium">Book as</label>
        <select id="bk-type" className={inp} value={type} onChange={(e) => { setType(e.target.value as typeof type); setCategoryId(""); setOtherId(""); }}>
          <option value={inflow ? "income" : "expense"}>{inflow ? "Income" : "Expense"}</option>
          <option value="transfer">Transfer {inflow ? "from" : "to"} another account</option>
        </select>
      </div>
      {type === "transfer" ? (
        <div>
          <label htmlFor="bk-other" className="mb-1 block text-xs font-medium">{inflow ? "Received from" : "Sent to"}</label>
          <select id="bk-other" className={inp} value={otherId} onChange={(e) => setOtherId(e.target.value)}>
            <option value="">Select…</option>
            {others.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
        </div>
      ) : (
        <div>
          <label htmlFor="bk-cat" className="mb-1 block text-xs font-medium">Category</label>
          <select id="bk-cat" className={inp} value={categoryId} onChange={(e) => setCategoryId(e.target.value)}>
            <option value="">Select…</option>
            {cats.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
        </div>
      )}
      <div>
        <label htmlFor="bk-desc" className="mb-1 block text-xs font-medium">Description</label>
        <input id="bk-desc" className={inp} value={description} maxLength={500} onChange={(e) => setDescription(e.target.value)} />
      </div>
    </Modal>
  );
}
