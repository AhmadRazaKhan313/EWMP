"use client";

import { useRef } from "react";
import { Download, Paperclip, Trash2 } from "lucide-react";
import { Button } from "@/components/atoms";
import { downloadAttachment, useAttachments, useDeleteAttachment, useUploadAttachment, type Bill } from "@/services/finance-purchases.service";
import { Modal } from "../sales/CustomerDialog";

const kb = (n: number) => (n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`);

export function AttachmentsDialog({ bill, canEdit, onClose }: { bill: Bill; canEdit: boolean; onClose: () => void }) {
  const files = useAttachments(bill.id);
  const upload = useUploadAttachment();
  const del = useDeleteAttachment();
  const input = useRef<HTMLInputElement>(null);
  const locked = bill.status === "void";

  return (
    <Modal title={`Files for ${bill.number}`} onClose={onClose} footer={<Button variant="outline" size="sm" onClick={onClose}>Close</Button>}>
      {(files.data?.length ?? 0) === 0 && !files.isLoading && <p className="text-sm text-[hsl(var(--foreground-muted))]">No files yet. Attach the vendor's invoice or receipt (PDF, image, Word or Excel, up to 10 MB).</p>}
      <ul className="space-y-2">
        {files.data?.map((a) => (
          <li key={a.id} className="flex items-center justify-between gap-3 text-sm">
            <span className="min-w-0 truncate">{a.file_name} <span className="text-xs text-[hsl(var(--foreground-muted))]">· {kb(a.size_bytes)}</span></span>
            <span className="flex shrink-0 gap-1">
              <button aria-label={`Download ${a.file_name}`} className="p-1" onClick={() => void downloadAttachment(bill.id, a)}><Download size={15} /></button>
              {canEdit && <button aria-label={`Remove ${a.file_name}`} className="p-1" onClick={() => del.mutate({ billId: bill.id, id: a.id })}><Trash2 size={15} /></button>}
            </span>
          </li>
        ))}
      </ul>
      {canEdit && !locked && (
        <>
          <input ref={input} type="file" aria-label="Choose file" hidden accept=".pdf,.png,.jpg,.jpeg,.webp,.docx,.xlsx"
            onChange={(e) => { const f = e.target.files?.[0]; if (f) upload.mutate({ billId: bill.id, file: f }); e.target.value = ""; }} />
          <Button variant="outline" size="sm" icon={<Paperclip size={14} />} disabled={upload.isPending} onClick={() => input.current?.click()}>
            {upload.isPending ? "Uploading…" : "Attach a file"}
          </Button>
        </>
      )}
    </Modal>
  );
}
