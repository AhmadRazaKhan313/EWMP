"use client";

import { useRef, useState } from "react";
import { CheckCircle2, FileText, Loader2, Lock, Trash2, Upload, XCircle } from "lucide-react";
import { cn } from "@/utils/cn";
import { DOCUMENT_TYPE_LABELS, type DocumentType } from "@/services/employeeDocuments.service";
import { Badge } from "@/components/atoms";
import { DOC_ACCEPT, formatFileSize, validateDocumentFile, type StagedDoc } from "./wizard";

export type DocStatus = "pending" | "uploading" | "done" | "failed";

const input =
  "h-11 w-full rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 text-sm outline-none transition-colors " +
  "placeholder:text-[hsl(var(--foreground-muted))] hover:border-[hsl(var(--border-strong))] focus:border-[hsl(var(--brand-300))] focus:ring-4 focus:ring-[hsl(var(--brand-100))]";

function newId() {
  return typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : String(Math.random()).slice(2);
}

/**
 * Documents are held in memory until the employee exists (they belong to an
 * employee id), then uploaded by the wizard. Nothing here claims an upload has
 * happened: the badge says "Pending" until the wizard reports "Uploaded".
 */
export function DocumentsStep({
  docs, status, locked, onAdd, onRemove,
}: {
  docs: StagedDoc[];
  status: Record<string, DocStatus>;
  locked: boolean;
  onAdd: (d: StagedDoc) => void;
  onRemove: (id: string) => void;
}) {
  const [type, setType] = useState("");
  const [title, setTitle] = useState("");
  const [expiry, setExpiry] = useState("");
  const [notes, setNotes] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [errors, setErrors] = useState<{ type?: string; title?: string; file?: string }>({});
  const fileRef = useRef<HTMLInputElement>(null);

  function add() {
    const next: typeof errors = {};
    if (!type) next.type = "Select a document type";
    if (!title.trim()) next.title = "Enter a title";
    const fileError = validateDocumentFile(file);
    if (fileError) next.file = fileError;
    setErrors(next);
    if (Object.keys(next).length || !file) return;
    onAdd({ id: newId(), file, document_type: type, title: title.trim(), expiry_date: expiry || undefined, notes: notes.trim() || undefined });
    setType(""); setTitle(""); setExpiry(""); setNotes(""); setFile(null); setErrors({});
    if (fileRef.current) fileRef.current.value = "";
  }

  return (
    <div className="space-y-5">
      <p className="flex items-start gap-2 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background-subtle))] p-3 text-xs text-[hsl(var(--foreground-muted))]">
        <Lock size={13} aria-hidden className="mt-0.5 shrink-0" />
        Files are held here until the employee is created, then uploaded automatically. Once uploaded, a document is locked and can only be removed by an HR admin.
      </p>

      {!locked && (
        <fieldset
          // Enter here adds the document; it must not submit the wizard form around it.
          onKeyDown={(e) => { if (e.key === "Enter" && (e.target as HTMLElement).tagName !== "BUTTON") { e.preventDefault(); add(); } }}
          className="space-y-4 rounded-xl border border-[hsl(var(--border))] p-4">
          <legend className="px-1 text-sm font-semibold">Add a document</legend>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="doc-type" className="mb-1.5 block text-sm font-medium">Document type <span aria-hidden className="text-[hsl(var(--destructive))]">*</span></label>
              <select id="doc-type" value={type} onChange={(e) => setType(e.target.value)} aria-invalid={!!errors.type} className={input}>
                <option value="">Select type</option>
                {Object.entries(DOCUMENT_TYPE_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
              {errors.type && <p role="alert" className="mt-1.5 text-xs text-[hsl(var(--destructive))]">{errors.type}</p>}
            </div>
            <div>
              <label htmlFor="doc-title" className="mb-1.5 block text-sm font-medium">Title <span aria-hidden className="text-[hsl(var(--destructive))]">*</span></label>
              <input id="doc-title" value={title} onChange={(e) => setTitle(e.target.value)} aria-invalid={!!errors.title}
                placeholder="e.g. CNIC — Front Side" className={input} />
              {errors.title && <p role="alert" className="mt-1.5 text-xs text-[hsl(var(--destructive))]">{errors.title}</p>}
            </div>
          </div>

          <div>
            <label htmlFor="doc-file" className="mb-1.5 block text-sm font-medium">File <span aria-hidden className="text-[hsl(var(--destructive))]">*</span></label>
            <input
              ref={fileRef} id="doc-file" type="file" accept={DOC_ACCEPT} aria-invalid={!!errors.file}
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="block w-full rounded-lg border border-dashed border-[hsl(var(--border-strong))] bg-[hsl(var(--background-subtle))] px-3 py-3 text-sm file:mr-3 file:rounded-md file:border-0 file:bg-[hsl(var(--brand-50))] file:px-3 file:py-1.5 file:text-xs file:font-semibold file:text-[hsl(var(--brand-700))]"
            />
            {errors.file
              ? <p role="alert" className="mt-1.5 text-xs text-[hsl(var(--destructive))]">{errors.file}</p>
              : <p className="mt-1.5 text-xs text-[hsl(var(--foreground-muted))]">PDF, JPG, PNG, WEBP, DOC, DOCX — max 15 MB{file ? ` · ${file.name} (${formatFileSize(file.size)})` : ""}</p>}
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="doc-expiry" className="mb-1.5 block text-sm font-medium">Expiry date <span className="font-normal text-[hsl(var(--foreground-muted))]">(optional)</span></label>
              <input id="doc-expiry" type="date" value={expiry} onChange={(e) => setExpiry(e.target.value)} className={input} />
            </div>
            <div>
              <label htmlFor="doc-notes" className="mb-1.5 block text-sm font-medium">Notes <span className="font-normal text-[hsl(var(--foreground-muted))]">(optional)</span></label>
              <input id="doc-notes" value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Any additional context" className={input} />
            </div>
          </div>

          <div className="flex justify-end">
            <button type="button" onClick={add}
              className="inline-flex h-10 items-center gap-2 rounded-lg bg-[hsl(var(--primary))] px-4 text-sm font-semibold text-[hsl(var(--primary-foreground))] hover:bg-[hsl(var(--primary-hover))] focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-[hsl(var(--brand-100))]">
              <Upload size={14} aria-hidden /> Add to list
            </button>
          </div>
        </fieldset>
      )}

      <ul className="space-y-2" aria-label="Documents to upload">
        {docs.length === 0 && (
          <li className="rounded-xl border border-dashed border-[hsl(var(--border))] p-6 text-center text-sm text-[hsl(var(--foreground-muted))]">
            No documents added. You can skip this step and add documents later from the employee&apos;s profile.
          </li>
        )}
        {docs.map((d) => {
          const st = status[d.id] ?? "pending";
          return (
            <li key={d.id} className="flex items-center gap-3 rounded-xl border border-[hsl(var(--border))] p-3">
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[hsl(var(--secondary))]">
                <FileText size={16} aria-hidden className="text-[hsl(var(--foreground-subtle))]" />
              </span>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">{d.title}</p>
                <p className="truncate text-xs text-[hsl(var(--foreground-muted))]">
                  {DOCUMENT_TYPE_LABELS[d.document_type as DocumentType]} · {d.file.name} · {formatFileSize(d.file.size)}
                  {d.expiry_date ? ` · expires ${d.expiry_date}` : ""}
                </p>
              </div>
              <span className={cn("flex shrink-0 items-center gap-1.5 text-xs font-medium",
                st === "done" && "text-[hsl(var(--success))]", st === "failed" && "text-[hsl(var(--destructive))]")}>
                {st === "uploading" && <><Loader2 size={13} aria-hidden className="animate-spin" /> Uploading…</>}
                {st === "done" && <><CheckCircle2 size={13} aria-hidden /> Uploaded</>}
                {st === "failed" && <><XCircle size={13} aria-hidden /> Failed</>}
                {st === "pending" && <Badge variant="outline">Pending</Badge>}
              </span>
              {st !== "done" && st !== "uploading" && (
                <button type="button" onClick={() => onRemove(d.id)} aria-label={`Remove ${d.title}`}
                  className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-[hsl(var(--foreground-muted))] hover:bg-[hsl(var(--status-error-bg))] hover:text-[hsl(var(--destructive))]">
                  <Trash2 size={14} aria-hidden />
                </button>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
