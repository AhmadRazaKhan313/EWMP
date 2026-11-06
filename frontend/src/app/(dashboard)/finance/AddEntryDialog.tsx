"use client";

import { useMemo, useState } from "react";
import { X } from "lucide-react";
import { Button } from "@/components/atoms";
import {
  categoriesFor, isMoneyAccount, useAddProvider, useCreateAccount, useCreateTransaction, useProviders,
  type FinAccount, type TxnType,
} from "@/services/finance.service";
import { cn } from "@/utils/cn";

const inp =
  "w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-2 text-sm outline-none focus:border-[hsl(var(--brand-300))] focus:ring-4 focus:ring-[hsl(var(--brand-100))]";
const NEW = "__new__";
const today = () => new Date().toISOString().slice(0, 10);

export function AddEntryDialog({
  accounts, defaultType = "expense", onClose,
}: { accounts: FinAccount[]; defaultType?: TxnType; onClose: () => void }) {
  const create = useCreateTransaction();
  const createAccount = useCreateAccount();
  const addProvider = useAddProvider();
  const money = useMemo(() => accounts.filter(isMoneyAccount), [accounts]);
  const [type, setType] = useState<TxnType>(defaultType);
  const [date, setDate] = useState(today());
  const [amount, setAmount] = useState("");
  const [accountId, setAccountId] = useState(money[0]?.id ?? "");
  const [toAccountId, setToAccountId] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [newCategory, setNewCategory] = useState("");
  const [description, setDescription] = useState("");
  const [provider, setProvider] = useState("");
  const [newProvider, setNewProvider] = useState("");
  const [accountNo, setAccountNo] = useState("");
  const [tid, setTid] = useState("");

  const kind = accounts.find((a) => a.id === accountId)?.money_kind;
  const showDetails = type !== "transfer" && (kind === "bank" || kind === "wallet");
  const providers = useProviders(showDetails ? (kind as "bank" | "wallet") : undefined);
  const addingProvider = provider === NEW;
  const providerName = (addingProvider ? newProvider : provider).trim();
  const noun = kind === "wallet" ? "Wallet" : "Bank";
  const categories = useMemo(() => categoriesFor(accounts, type), [accounts, type]);
  const adding = categoryId === NEW;
  const amountOk = /^\d+(\.\d{1,2})?$/.test(amount) && parseFloat(amount) > 0;
  const ready =
    amountOk && !!accountId && !!date && (!showDetails || providerName.length > 0) &&
    (type === "transfer" ? !!toAccountId && toAccountId !== accountId : adding ? newCategory.trim().length > 0 : !!categoryId);

  async function submit() {
    let catId = categoryId;
    if (type !== "transfer" && adding) {
      const made = await createAccount.mutateAsync({ name: newCategory.trim(), type: type === "income" ? "income" : "expense" });
      catId = made.id;
    }
    if (showDetails && addingProvider) {
      await addProvider.mutateAsync({ kind: kind as "bank" | "wallet", name: providerName });
    }
    await create.mutateAsync({
      type, date, amount, account_id: accountId,
      payment_provider: showDetails ? providerName : undefined,
      payment_account_no: showDetails && accountNo.trim() ? accountNo.trim() : undefined,
      payment_tid: showDetails && tid.trim() ? tid.trim() : undefined,
      category_id: type === "transfer" ? undefined : catId,
      to_account_id: type === "transfer" ? toAccountId : undefined,
      description: description.trim() || undefined,
    });
    onClose();
  }

  const busy = create.isPending || createAccount.isPending || addProvider.isPending;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose} role="presentation">
      <div
        role="dialog" aria-modal="true" aria-label="Add entry" onClick={(e) => e.stopPropagation()}
        className="w-full max-w-lg rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] shadow-xl"
      >
        <div className="flex items-center justify-between border-b border-[hsl(var(--border))] p-5">
          <h3 className="font-heading text-base font-semibold">Add entry</h3>
          <button type="button" onClick={onClose} aria-label="Close" className="rounded p-1 hover:bg-[hsl(var(--secondary))]"><X size={16} /></button>
        </div>
        <div className="space-y-4 p-5">
          <div className="flex gap-1.5" role="group" aria-label="Entry type">
            {(["expense", "income", "transfer"] as TxnType[]).map((t) => (
              <button
                key={t} type="button" aria-pressed={type === t}
                onClick={() => { setType(t); setCategoryId(""); }}
                className={cn(
                  "h-9 flex-1 rounded-md text-sm font-semibold capitalize transition-colors",
                  type === t ? "bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]" : "bg-[hsl(var(--secondary))] text-[hsl(var(--foreground-muted))] hover:bg-[hsl(var(--secondary-hover))]",
                )}
              >{t}</button>
            ))}
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label htmlFor="fin-date" className="mb-1 block text-xs font-medium">Date</label>
              <input id="fin-date" type="date" value={date} onChange={(e) => setDate(e.target.value)} className={inp} />
            </div>
            <div>
              <label htmlFor="fin-amount" className="mb-1 block text-xs font-medium">Amount</label>
              <input id="fin-amount" inputMode="decimal" placeholder="0" value={amount} onChange={(e) => setAmount(e.target.value.replace(/,/g, ""))} className={inp} />
            </div>
            <div>
              <label htmlFor="fin-account" className="mb-1 block text-xs font-medium">{type === "transfer" ? "From account" : type === "income" ? "Received in" : "Paid from"}</label>
              <select id="fin-account" value={accountId} onChange={(e) => { setAccountId(e.target.value); setProvider(""); setNewProvider(""); setAccountNo(""); setTid(""); }} className={inp}>
                {money.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
              </select>
            </div>
            {type === "transfer" ? (
              <div>
                <label htmlFor="fin-to" className="mb-1 block text-xs font-medium">To account</label>
                <select id="fin-to" value={toAccountId} onChange={(e) => setToAccountId(e.target.value)} className={inp}>
                  <option value="">Select…</option>
                  {money.filter((a) => a.id !== accountId).map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
                </select>
              </div>
            ) : (
              <div>
                <label htmlFor="fin-category" className="mb-1 block text-xs font-medium">Category</label>
                <select id="fin-category" value={categoryId} onChange={(e) => setCategoryId(e.target.value)} className={inp}>
                  <option value="">Select…</option>
                  {categories.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
                  <option value={NEW}>+ New category…</option>
                </select>
              </div>
            )}
          </div>
          {adding && type !== "transfer" && (
            <div>
              <label htmlFor="fin-newcat" className="mb-1 block text-xs font-medium">New category name</label>
              <input id="fin-newcat" value={newCategory} onChange={(e) => setNewCategory(e.target.value)} className={inp} />
            </div>
          )}
          {showDetails && (
            <div className="space-y-4 rounded-lg border border-[hsl(var(--border))] p-3">
              <div>
                <label htmlFor="fin-provider" className="mb-1 block text-xs font-medium">{noun} name</label>
                <select id="fin-provider" value={provider} onChange={(e) => setProvider(e.target.value)} className={inp}>
                  <option value="">Select…</option>
                  {providers.data?.map((n) => <option key={n} value={n}>{n}</option>)}
                  <option value={NEW}>{`+ Add new ${noun.toLowerCase()}…`}</option>
                </select>
              </div>
              {addingProvider && (
                <div>
                  <label htmlFor="fin-newprovider" className="mb-1 block text-xs font-medium">{`New ${noun.toLowerCase()} name`}</label>
                  <input id="fin-newprovider" value={newProvider} maxLength={100} onChange={(e) => setNewProvider(e.target.value)} className={inp} />
                </div>
              )}
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label htmlFor="fin-accno" className="mb-1 block text-xs font-medium">{kind === "wallet" ? "Wallet number" : "Account no"}</label>
                  <input id="fin-accno" value={accountNo} maxLength={60} onChange={(e) => setAccountNo(e.target.value)} className={inp} />
                </div>
                <div>
                  <label htmlFor="fin-tid" className="mb-1 block text-xs font-medium">TID (transaction ID)</label>
                  <input id="fin-tid" value={tid} maxLength={100} onChange={(e) => setTid(e.target.value)} className={inp} />
                </div>
              </div>
            </div>
          )}
          <div>
            <label htmlFor="fin-desc" className="mb-1 block text-xs font-medium">Description</label>
            <input id="fin-desc" value={description} maxLength={500} onChange={(e) => setDescription(e.target.value)} className={inp} />
          </div>
        </div>
        <div className="flex justify-end gap-2 border-t border-[hsl(var(--border))] p-4">
          <Button variant="outline" size="sm" onClick={onClose}>Cancel</Button>
          <Button size="sm" disabled={!ready || busy} onClick={() => void submit()}>{busy ? "Saving…" : "Save entry"}</Button>
        </div>
      </div>
    </div>
  );
}
