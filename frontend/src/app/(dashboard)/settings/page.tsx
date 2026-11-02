"use client";

import { useEffect, useState } from "react";
import { Building2, Users, Shield, Bell, Palette, Key, Webhook, Bot, Coffee } from "lucide-react";
import { Card, PageHeader } from "@/components/atoms";
import { RolesManager } from "@/components/organisms/RolesManager";
import { AIConfigSettings } from "@/components/organisms/AIConfigSettings";
import { OrganizationSettingsForm } from "@/components/organisms/OrganizationSettingsForm";
import { BreakSettings, usePendingBreakRequests } from "@/components/organisms/BreakSettings";
import { OrganizationLogoCard } from "@/components/organization/OrganizationLogoCard";
import { NotificationSettings } from "@/components/organisms/NotificationSettings";

const TABS = [
  { id: "general",       label: "General",       icon: Building2 },
  { id: "members",       label: "Members",       icon: Users },
  { id: "roles",         label: "Roles",         icon: Shield },
  { id: "break",         label: "Break",         icon: Coffee },
  { id: "ai",            label: "AI Assistant",  icon: Bot },
  { id: "notifications", label: "Notifications", icon: Bell },
  { id: "appearance",    label: "Appearance",    icon: Palette },
  { id: "api",           label: "API Keys",      icon: Key },
  { id: "webhooks",      label: "Webhooks",      icon: Webhook },
];

export default function SettingsPage() {
  const [activeTab, setActiveTab] = useState("general");
  const pendingBreaks = usePendingBreakRequests().data?.pending_count ?? 0;

  // Links like /settings?tab=notifications open that tab.
  useEffect(() => {
    const wanted = new URLSearchParams(window.location.search).get("tab");
    if (wanted && TABS.some((t) => t.id === wanted)) setActiveTab(wanted);
  }, []);

  return (
    <div className="space-y-6">
      <PageHeader title="Settings" description="Manage your organization configuration and preferences." />

      <div className="flex gap-6">
        {/* Sidebar nav */}
        <nav className="flex w-48 shrink-0 flex-col gap-0.5">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium text-left transition-colors ${
                activeTab === tab.id
                  ? "bg-[hsl(var(--accent))] text-[hsl(var(--foreground))]"
                  : "text-[hsl(var(--foreground-muted))] hover:bg-[hsl(var(--accent))] hover:text-[hsl(var(--foreground))]"
              }`}
            >
              <tab.icon size={15} />
              {tab.label}
              {tab.id === "break" && pendingBreaks > 0 && (
                <span className="ml-auto rounded-full bg-[hsl(var(--destructive))] px-1.5 text-[10px] font-semibold text-white">{pendingBreaks}</span>
              )}
            </button>
          ))}
        </nav>

        {/* Content */}
        <div className="flex-1">
          {activeTab === "general" && (
            <div className="space-y-4">
              <OrganizationLogoCard />
              <OrganizationSettingsForm />
            </div>
          )}

          {activeTab === "roles" && <RolesManager />}

          {activeTab === "break" && <BreakSettings />}

          {activeTab === "ai" && <AIConfigSettings />}

          {activeTab === "notifications" && <NotificationSettings />}

          {(activeTab === "members" || activeTab === "appearance" || activeTab === "api" || activeTab === "webhooks") && (
            <Card>
              <div className="flex flex-col items-center justify-center py-12 text-center">
                <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-[hsl(var(--secondary))]">
                  {(() => { const T = TABS.find(t => t.id === activeTab); return T ? <T.icon size={22} className="text-[hsl(var(--foreground-muted))]" /> : null; })()}
                </div>
                <p className="font-medium text-sm">{TABS.find(t => t.id === activeTab)?.label} settings</p>
                <p className="text-xs text-[hsl(var(--foreground-muted))] mt-1">Coming in next sprint</p>
              </div>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}