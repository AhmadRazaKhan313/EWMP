"use client";

import { useState } from "react";
import { Building2, Users, Shield, Bell, Palette, Key, Webhook, Bot } from "lucide-react";
import { Button, Card, PageHeader } from "@/components/atoms";
import { useAuthStore } from "@/store/auth.store";
import { RolesManager } from "@/components/organisms/RolesManager";
import { AIConfigSettings } from "@/components/organisms/AIConfigSettings";

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

function SettingRow({ label, description, children }: { label: string; description?: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between py-4 border-b border-[hsl(var(--border))] last:border-0">
      <div>
        <p className="text-sm font-medium">{label}</p>
        {description && <p className="text-xs text-[hsl(var(--foreground-muted))] mt-0.5">{description}</p>}
      </div>
      <div className="ml-8 shrink-0">{children}</div>
    </div>
  );
}

function Toggle({ defaultChecked = false }: { defaultChecked?: boolean }) {
  const [on, setOn] = useState(defaultChecked);
  return (
    <button
      onClick={() => setOn((v) => !v)}
      className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full transition-colors ${on ? "bg-[hsl(var(--primary))]" : "bg-[hsl(var(--secondary))]"}`}
    >
      <span className={`inline-block h-4 w-4 translate-y-0.5 rounded-full bg-white shadow transition-transform ${on ? "translate-x-4" : "translate-x-0.5"}`} />
    </button>
  );
}

export default function SettingsPage() {
  const [activeTab, setActiveTab] = useState("general");
  const { user } = useAuthStore();

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
          {activeTab === "general" && (
            <Card padding={false}>
              <div className="border-b border-[hsl(var(--border))] px-5 py-4">
                <h3 className="font-heading text-sm font-semibold">Organization Settings</h3>
              </div>
              <div className="px-5">
                <SettingRow label="Organization Name" description="The display name of your organization">
                  <input defaultValue="My Organization" className="h-8 w-56 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 text-sm outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]" />
                </SettingRow>
                <SettingRow label="Default Timezone" description="Used for attendance and scheduling">
                  <select className="h-8 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-2 text-sm outline-none">
                    <option>UTC</option>
                    <option>Asia/Karachi</option>
                    <option>America/New_York</option>
                    <option>Europe/London</option>
                  </select>
                </SettingRow>
                <SettingRow label="Default Currency">
                  <select className="h-8 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-2 text-sm outline-none">
                    <option>USD</option>
                    <option>PKR</option>
                    <option>EUR</option>
                    <option>GBP</option>
                  </select>
                </SettingRow>
                <SettingRow label="Work Week" description="Define which days are working days">
                  <div className="flex gap-1">
                    {["M", "T", "W", "T", "F", "S", "S"].map((d, i) => (
                      <button
                        key={i}
                        className={`h-7 w-7 rounded-full text-xs font-medium ${i < 5 ? "bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]" : "bg-[hsl(var(--secondary))] text-[hsl(var(--foreground-muted))]"}`}
                      >
                        {d}
                      </button>
                    ))}
                  </div>
                </SettingRow>
              </div>
              <div className="border-t border-[hsl(var(--border))] px-5 py-4">
                <Button size="sm">Save Changes</Button>
              </div>
            </Card>
          )}

          {activeTab === "notifications" && (
            <Card padding={false}>
              <div className="border-b border-[hsl(var(--border))] px-5 py-4">
                <h3 className="font-heading text-sm font-semibold">Notification Preferences</h3>
              </div>
              <div className="px-5">
                <SettingRow label="Leave Requests" description="Notify when employees submit leave">
                  <Toggle defaultChecked />
                </SettingRow>
                <SettingRow label="Attendance Alerts" description="Notify on late arrivals or absences">
                  <Toggle defaultChecked />
                </SettingRow>
                <SettingRow label="Device Alerts" description="Notify when devices go offline or have health issues">
                  <Toggle defaultChecked />
                </SettingRow>
                <SettingRow label="Payroll Reminders" description="Remind before payroll due dates">
                  <Toggle defaultChecked />
                </SettingRow>
                <SettingRow label="New Employees" description="Notify on successful employee onboarding">
                  <Toggle />
                </SettingRow>
              </div>
              <div className="border-t border-[hsl(var(--border))] px-5 py-4">
                <Button size="sm">Save Preferences</Button>
              </div>
            </Card>
          )}

          {activeTab === "api" && (
            <Card padding={false}>
              <div className="flex items-center justify-between border-b border-[hsl(var(--border))] px-5 py-4">
                <h3 className="font-heading text-sm font-semibold">API Keys</h3>
                <Button size="sm" icon={<Key size={13} />}>Create Key</Button>
              </div>
              <div className="px-5 py-4">
                <p className="text-sm text-[hsl(var(--foreground-muted))]">
                  API keys allow external applications to access EWMP data securely.
                  Each key can be scoped to specific permissions.
                </p>
                <div className="mt-4 rounded-lg border border-[hsl(var(--border))] p-4 text-center text-sm text-[hsl(var(--foreground-muted))]">
                  No API keys yet. Create one to get started.
                </div>
              </div>
            </Card>
          )}

          {activeTab === "roles" && <RolesManager />}

          {activeTab === "ai" && <AIConfigSettings />}

          {(activeTab === "members" || activeTab === "appearance" || activeTab === "webhooks") && (
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