"use client";

import { useState } from "react";
import { Building2, Users, Shield, Bell, Palette, Key, Webhook, Bot } from "lucide-react";
import { Card, PageHeader } from "@/components/atoms";
import { RolesManager } from "@/components/organisms/RolesManager";
import { AIConfigSettings } from "@/components/organisms/AIConfigSettings";
import { OrganizationSettingsForm } from "@/components/organisms/OrganizationSettingsForm";

const TABS = [
  { id: "general",       label: "General",       icon: Building2 },
  { id: "members",       label: "Members",       icon: Users },
  { id: "roles",         label: "Roles",         icon: Shield },
  { id: "ai",            label: "AI Assistant",  icon: Bot },
  { id: "notifications", label: "Notifications", icon: Bell },
  { id: "appearance",    label: "Appearance",    icon: Palette },
  { id: "api",           label: "API Keys",      icon: Key },
  { id: "webhooks",      label: "Webhooks",      icon: Webhook },
];

export default function SettingsPage() {
  const [activeTab, setActiveTab] = useState("general");

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
            </button>
          ))}
        </nav>

        {/* Content */}
        <div className="flex-1">
          {activeTab === "general" && <OrganizationSettingsForm />}

          {activeTab === "roles" && <RolesManager />}

          {activeTab === "ai" && <AIConfigSettings />}

          {(activeTab === "members" || activeTab === "notifications" || activeTab === "appearance" || activeTab === "api" || activeTab === "webhooks") && (
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