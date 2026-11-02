"use client";

import { Shield } from "lucide-react";
import { OrgLogoImage } from "./OrgLogoImage";

/** Sidebar brand lockup: the organization's logo, else the EWMP mark + name. */
export function BrandMark() {
  return (
    <div className="flex items-center gap-2 px-5 pb-5 pt-5">
      <OrgLogoImage
        className="h-8 max-w-[200px] object-contain"
        fallback={
          <>
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-[hsl(var(--sidebar-border))] bg-[hsl(var(--background))] shadow-[var(--shadow-xs)]">
              <Shield size={18} strokeWidth={2} className="text-[hsl(var(--primary))]" />
            </div>
            <span className="font-heading text-[22px] font-bold leading-8 tracking-tight text-[hsl(var(--foreground))]">
              EWMP
            </span>
          </>
        }
      />
    </div>
  );
}
