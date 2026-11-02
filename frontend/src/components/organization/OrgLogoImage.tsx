"use client";

import { useEffect, useState } from "react";
import { useAuthStore } from "@/store/auth.store";
import { resolveMediaUrl } from "@/utils/media";
import { LOGO_CHANGED_EVENT } from "@/services/organization.service";

/**
 * The signed-in user's organization logo, or `fallback` (default nothing)
 * while it is loading or when the organization has none. The logo route is
 * public and revalidated on every use, so this needs no data fetching, only
 * the organization id the session already has.
 */
export function OrgLogoImage({
  className, fallback = null,
}: { className?: string; fallback?: React.ReactNode }) {
  const orgId = useAuthStore((s) => s.user?.organization_id);
  const [state, setState] = useState<"loading" | "ok" | "none">("loading");
  const [version, setVersion] = useState(0);

  useEffect(() => {
    const again = () => { setState("loading"); setVersion((v) => v + 1); };
    window.addEventListener(LOGO_CHANGED_EVENT, again);
    return () => window.removeEventListener(LOGO_CHANGED_EVENT, again);
  }, []);

  if (!orgId) return <>{fallback}</>;
  const src = resolveMediaUrl(`/api/v1/organization/logo/${orgId}`);
  return (
    <>
      {state !== "ok" && fallback}
      {/* Kept mounted (hidden) while loading so onLoad / onError can fire. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        key={version}
        src={`${src}${version ? `?v=${version}` : ""}`}
        alt="Organization logo"
        data-testid="org-logo"
        className={state === "ok" ? className : "hidden"}
        onLoad={() => setState("ok")}
        onError={() => setState("none")}
      />
    </>
  );
}
