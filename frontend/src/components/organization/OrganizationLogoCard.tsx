"use client";

import { useRef } from "react";
import { Image as ImageIcon, Loader2, Trash2, Upload } from "lucide-react";
import { toast } from "sonner";
import { Button, Card } from "@/components/atoms";
import { useAuthStore } from "@/store/auth.store";
import { resolveMediaUrl } from "@/utils/media";
import {
  logoProblem,
  useDeleteOrganizationLogo,
  useOrganizationSettings,
  useUploadOrganizationLogo,
} from "@/services/organization.service";

function message(err: unknown): string {
  return (err as { response?: { data?: { message?: string } } })?.response?.data?.message ?? "Couldn't update the logo";
}

/** Settings -> General: upload / replace / remove the organization logo (needs settings.manage). */
export function OrganizationLogoCard() {
  const canManage = useAuthStore((s) => s.hasPermission)("settings.manage");
  const { data: org } = useOrganizationSettings();
  const upload = useUploadOrganizationLogo();
  const remove = useDeleteOrganizationLogo();
  const input = useRef<HTMLInputElement>(null);
  const busy = upload.isPending || remove.isPending;
  const logo = resolveMediaUrl(org?.logo_url);

  function pick(file: File | undefined) {
    if (!file) return;
    const problem = logoProblem(file);
    if (problem) {
      toast.error(problem);
      return;
    }
    upload.mutate(file, {
      onSuccess: () => toast.success("Logo updated"),
      onError: (err) => toast.error(message(err)),
    });
  }

  return (
    <Card padding={false}>
      <div className="flex flex-wrap items-center gap-4 px-5 py-4">
        <div className="flex h-16 w-40 shrink-0 items-center justify-center overflow-hidden rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--background-subtle))]">
          {logo ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={logo} alt="Organization logo" className="max-h-14 max-w-36 object-contain" />
          ) : (
            <ImageIcon size={22} className="text-[hsl(var(--foreground-muted))]" aria-hidden />
          )}
        </div>
        <div className="min-w-0 flex-1">
          <h3 className="font-heading text-sm font-semibold">Organization logo</h3>
          <p className="mt-0.5 text-xs text-[hsl(var(--foreground-muted))]">
            Shown in the sidebar and on payslips. PNG, JPEG, WebP or SVG, up to 2 MB.
            {!canManage && " Changing it needs the “Manage Organization Settings” permission."}
          </p>
        </div>
        {canManage && (
          <div className="flex gap-2">
            <input
              ref={input}
              type="file"
              accept="image/png,image/jpeg,image/webp,image/svg+xml"
              aria-label="Upload organization logo"
              className="sr-only"
              onChange={(e) => { pick(e.target.files?.[0]); e.target.value = ""; }}
            />
            <Button variant="outline" disabled={busy} onClick={() => input.current?.click()}>
              {upload.isPending ? <Loader2 size={14} className="mr-1.5 animate-spin" /> : <Upload size={14} className="mr-1.5" />}
              {logo ? "Replace" : "Upload"}
            </Button>
            {logo && (
              <Button
                variant="ghost"
                disabled={busy}
                onClick={() => remove.mutate(undefined, {
                  onSuccess: () => toast.success("Logo removed"),
                  onError: (err) => toast.error(message(err)),
                })}
              >
                <Trash2 size={14} className="mr-1.5" /> Remove
              </Button>
            )}
          </div>
        )}
      </div>
    </Card>
  );
}
