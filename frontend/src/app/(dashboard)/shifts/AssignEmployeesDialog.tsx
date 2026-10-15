"use client";

import { useEffect, useState } from "react";
import { Search, X } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import apiClient from "@/services/api-client";
import { Button } from "@/components/atoms";

interface RosterEmployee {
  id: string;
  employee_code: string;
  name: string;
  department_name: string | null;
  current_shift_id: string | null;
  current_shift_name: string | null;
}

interface Roster {
  shift: { id: string; name: string; code: string };
  assigned: RosterEmployee[];
  others: RosterEmployee[];
}

/**
 * Choose which employees work a shift. The list you save is the WHOLE roster:
 * everyone ticked is put on this shift (leaving whatever shift they had) and
 * anyone unticked is taken off it. (PUT /shifts/{id}/employees)
 */
export function AssignEmployeesDialog({
  shift,
  onClose,
}: {
  shift: { id: string; name: string };
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  // null until the first (unfiltered) load tells us who is on the shift already.
  const [selected, setSelected] = useState<Set<string> | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["shift-roster", shift.id, search],
    queryFn: async () => {
      const { data } = await apiClient.get<Roster>(`/shifts/${shift.id}/employees`, {
        params: search ? { search } : {},
      });
      return data;
    },
    placeholderData: (prev) => prev,
  });

  // Seed the selection from the shift's current roster exactly once. Later
  // searches only filter what is shown; they never change who is selected.
  useEffect(() => {
    if (selected === null && data && !search) {
      setSelected(new Set(data.assigned.map((e) => e.id)));
    }
  }, [data, selected, search]);

  const save = useMutation({
    mutationFn: async () =>
      (
        await apiClient.put<{ assigned: number; cleared: number }>(`/shifts/${shift.id}/employees`, {
          employee_ids: Array.from(selected ?? []),
        })
      ).data,
    onSuccess: (r) => {
      toast.success(`${shift.name}: ${r.assigned} employee${r.assigned === 1 ? "" : "s"} assigned` + (r.cleared ? `, ${r.cleared} removed` : ""));
      void qc.invalidateQueries({ queryKey: ["shifts"] });
      void qc.invalidateQueries({ queryKey: ["shift-roster"] });
      void qc.invalidateQueries({ queryKey: ["employees"] });
      void qc.invalidateQueries({ queryKey: ["attendance-daily"] });
      onClose();
    },
    onError: (err: unknown) => {
      const msg = (err as { response?: { data?: { message?: string } } })?.response?.data?.message;
      toast.error(msg ?? "Couldn't update the shift. Please try again.");
    },
  });

  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev ?? []);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const everyone = [...(data?.assigned ?? []), ...(data?.others ?? [])];
  const count = selected?.size ?? 0;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
      role="presentation"
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`Assign employees to ${shift.name}`}
        onClick={(e) => e.stopPropagation()}
        className="flex max-h-[85vh] w-full max-w-lg flex-col rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] shadow-xl"
      >
        <div className="flex items-start justify-between border-b border-[hsl(var(--border))] p-5">
          <div>
            <h3 className="font-heading text-base font-semibold">Assign employees</h3>
            <p className="text-xs text-[hsl(var(--foreground-muted))]">
              {shift.name} — tick everyone who works this shift. Moving someone here takes them off their current shift.
            </p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="rounded p-1 hover:bg-[hsl(var(--secondary))]">
            <X size={16} />
          </button>
        </div>

        <div className="border-b border-[hsl(var(--border))] p-3">
          <div className="relative">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[hsl(var(--foreground-muted))]" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search by name or code…"
              className="h-9 w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] pl-9 pr-3 text-sm outline-none focus:border-[hsl(var(--brand-300))] focus:ring-4 focus:ring-[hsl(var(--brand-100))]"
            />
          </div>
        </div>

        <div className="min-h-[200px] flex-1 overflow-y-auto p-2">
          {isLoading && !data ? (
            <p className="p-4 text-sm text-[hsl(var(--foreground-muted))]">Loading…</p>
          ) : everyone.length === 0 ? (
            <p className="p-4 text-sm text-[hsl(var(--foreground-muted))]">No employees match.</p>
          ) : (
            everyone.map((e) => {
              const checked = selected?.has(e.id) ?? false;
              const elsewhere = e.current_shift_id && e.current_shift_id !== shift.id;
              return (
                <label
                  key={e.id}
                  className="flex cursor-pointer items-center gap-3 rounded-md px-3 py-2 hover:bg-[hsl(var(--secondary))]"
                >
                  <input type="checkbox" checked={checked} onChange={() => toggle(e.id)} />
                  <span className="flex-1">
                    <span className="block text-sm font-medium">{e.name}</span>
                    <span className="block text-xs text-[hsl(var(--foreground-muted))]">
                      {e.employee_code}
                      {e.department_name ? ` · ${e.department_name}` : ""}
                    </span>
                  </span>
                  {elsewhere && (
                    <span className="rounded-full bg-[hsl(var(--secondary))] px-2 py-0.5 text-[10px] text-[hsl(var(--foreground-muted))]">
                      now on {e.current_shift_name}
                    </span>
                  )}
                </label>
              );
            })
          )}
        </div>

        <div className="flex items-center justify-between border-t border-[hsl(var(--border))] p-4">
          <span className="text-xs text-[hsl(var(--foreground-muted))]">{count} selected</span>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={onClose}>
              Cancel
            </Button>
            <Button size="sm" disabled={selected === null || save.isPending} onClick={() => save.mutate()}>
              {save.isPending ? "Saving…" : "Save"}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
