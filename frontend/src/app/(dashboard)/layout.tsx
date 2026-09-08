"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/store/auth.store";
import { AppSidebar } from "@/components/organisms/AppSidebar";
import { AppTopbar } from "@/components/organisms/AppTopbar";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, isInitialized, isLoading, user } = useAuthStore();
  const router = useRouter();

  useEffect(() => {
    if (!isInitialized || isLoading) return;
    if (!isAuthenticated) {
      router.replace("/login");
      return;
    }
    // Platform admin without an org needs to set one up
    if (user?.is_platform_admin && !user?.organization_id) {
      const path = window.location.pathname;
      if (path !== "/admin-setup") {
        router.replace("/admin-setup");
      }
    }
  }, [isAuthenticated, isInitialized, isLoading, user, router]);

  if (!isInitialized || isLoading) {
    return <DashboardSkeleton />;
  }

  if (!isAuthenticated) return null;

  return (
    <div className="flex h-screen overflow-hidden bg-[hsl(var(--background-subtle))]">
      <AppSidebar />
      <div className="flex flex-1 flex-col overflow-hidden">
        <AppTopbar />
        <main className="flex-1 overflow-y-auto px-6 py-6">
          {children}
        </main>
      </div>
    </div>
  );
}

function DashboardSkeleton() {
  return (
    <div className="flex h-screen overflow-hidden">
      <div className="w-60 bg-[hsl(var(--sidebar-background))] flex flex-col gap-2 p-4">
        <div className="skeleton h-8 w-32 rounded-md mb-6" />
        {Array.from({ length: 10 }).map((_, i) => (
          <div key={i} className="skeleton h-8 w-full rounded-md" />
        ))}
      </div>
      <div className="flex flex-1 flex-col gap-4 p-6">
        <div className="skeleton h-12 w-full rounded-md" />
        <div className="grid grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="skeleton h-28 rounded-xl" />
          ))}
        </div>
        <div className="skeleton h-96 rounded-xl" />
      </div>
    </div>
  );
}