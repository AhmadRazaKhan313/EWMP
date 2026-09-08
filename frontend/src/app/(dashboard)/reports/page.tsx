"use client";

import { useState } from "react";
import { BarChart2, Download, FileText, TrendingUp, Users, Calendar } from "lucide-react";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  LineChart, Line, PieChart, Pie, Cell, Legend,
} from "recharts";
import { Button, Card, CardHeader, PageHeader } from "@/components/atoms";

const attendanceData = [
  { month: "Jun", present: 215, absent: 18, leave: 9 },
  { month: "Jul", present: 228, absent: 12, leave: 14 },
  { month: "Aug", present: 220, absent: 15, leave: 11 },
  { month: "Sep", present: 235, absent: 8,  leave: 13 },
  { month: "Oct", present: 241, absent: 6,  leave: 10 },
  { month: "Nov", present: 238, absent: 9,  leave: 12 },
];

const headcountData = [
  { month: "Jun", headcount: 230 },
  { month: "Jul", headcount: 235 },
  { month: "Aug", headcount: 238 },
  { month: "Sep", headcount: 241 },
  { month: "Oct", headcount: 245 },
  { month: "Nov", headcount: 247 },
];

const departmentData = [
  { name: "Engineering",  value: 89 },
  { name: "Sales",        value: 54 },
  { name: "Operations",   value: 42 },
  { name: "HR",           value: 28 },
  { name: "Finance",      value: 21 },
  { name: "Other",        value: 13 },
];

const CHART_COLORS = ["#3b82f6", "#10b981", "#f59e0b", "#8b5cf6", "#ef4444", "#6b7280"];

const SAVED_REPORTS = [
  { name: "Monthly Attendance Summary",    type: "Attendance", last_run: "Nov 1, 2024" },
  { name: "Payroll Cost by Department",    type: "Payroll",    last_run: "Oct 31, 2024" },
  { name: "Headcount & Attrition Report",  type: "HR",         last_run: "Oct 31, 2024" },
  { name: "Device Compliance Report",      type: "Devices",    last_run: "Nov 2, 2024" },
];

export default function ReportsPage() {
  const [activeTab, setActiveTab] = useState<"overview" | "saved">("overview");

  return (
    <div className="space-y-6">
      <PageHeader
        title="Reports & Analytics"
        description="Workforce insights, trends, and exportable reports."
        action={
          <div className="flex gap-2">
            <Button variant="outline" icon={<Download size={14} />}>Export</Button>
            <Button icon={<FileText size={14} />}>New Report</Button>
          </div>
        }
      />

      {/* Tabs */}
      <div className="flex gap-1 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--background-subtle))] p-1 w-fit">
        {(["overview", "saved"] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`rounded-md px-4 py-1.5 text-sm font-medium transition-colors capitalize ${
              activeTab === tab
                ? "bg-[hsl(var(--background))] shadow-[var(--shadow-xs)] text-[hsl(var(--foreground))]"
                : "text-[hsl(var(--foreground-muted))] hover:text-[hsl(var(--foreground))]"
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      {activeTab === "overview" && (
        <div className="grid grid-cols-2 gap-6">
          {/* Attendance chart */}
          <div className="col-span-2 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] shadow-[var(--shadow-xs)]">
            <CardHeader title="Monthly Attendance" description="Present, absent, and on-leave breakdown" />
            <div className="p-5">
              <ResponsiveContainer width="100%" height={280}>
                <BarChart data={attendanceData} barCategoryGap="30%">
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                  <XAxis dataKey="month" tick={{ fontSize: 12 }} />
                  <YAxis tick={{ fontSize: 12 }} />
                  <Tooltip contentStyle={{ borderRadius: 8, border: "1px solid hsl(var(--border))", fontSize: 12 }} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <Bar dataKey="present" name="Present" fill="#10b981" radius={[3, 3, 0, 0]} />
                  <Bar dataKey="absent"  name="Absent"  fill="#ef4444" radius={[3, 3, 0, 0]} />
                  <Bar dataKey="leave"   name="On Leave" fill="#f59e0b" radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Headcount trend */}
          <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] shadow-[var(--shadow-xs)]">
            <CardHeader title="Headcount Trend" description="Total active employees over time" />
            <div className="p-5">
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={headcountData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                  <XAxis dataKey="month" tick={{ fontSize: 12 }} />
                  <YAxis tick={{ fontSize: 12 }} domain={["auto", "auto"]} />
                  <Tooltip contentStyle={{ borderRadius: 8, border: "1px solid hsl(var(--border))", fontSize: 12 }} />
                  <Line type="monotone" dataKey="headcount" stroke="#3b82f6" strokeWidth={2} dot={{ r: 3 }} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Department distribution */}
          <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] shadow-[var(--shadow-xs)]">
            <CardHeader title="By Department" description="Employee distribution across departments" />
            <div className="p-5">
              <ResponsiveContainer width="100%" height={220}>
                <PieChart>
                  <Pie data={departmentData} cx="50%" cy="50%" innerRadius={55} outerRadius={85} paddingAngle={3} dataKey="value">
                    {departmentData.map((_, i) => (
                      <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip contentStyle={{ borderRadius: 8, border: "1px solid hsl(var(--border))", fontSize: 12 }} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                </PieChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>
      )}

      {activeTab === "saved" && (
        <div className="space-y-2">
          {SAVED_REPORTS.map((r, i) => (
            <div
              key={i}
              className="flex items-center justify-between rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-5 py-4 shadow-[var(--shadow-xs)] hover:border-[hsl(var(--border-strong))] transition-colors"
            >
              <div className="flex items-center gap-3">
                <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[hsl(var(--secondary))]">
                  <FileText size={16} className="text-[hsl(var(--foreground-subtle))]" />
                </div>
                <div>
                  <p className="font-medium text-sm">{r.name}</p>
                  <p className="text-xs text-[hsl(var(--foreground-muted))]">
                    {r.type} · Last run: {r.last_run}
                  </p>
                </div>
              </div>
              <Button variant="outline" size="sm" icon={<Download size={13} />}>
                Export
              </Button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
