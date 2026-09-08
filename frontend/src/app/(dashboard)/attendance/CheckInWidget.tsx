"use client";

import { useEffect, useState } from "react";
import { MapPin, LogIn, LogOut, Loader2, Clock, Coffee } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import apiClient from "@/services/api-client";
import { Card } from "@/components/atoms";

interface ActiveWorkSession {
  id: string;
  employee_id: string;
  started_at: string;
  ended_at: string | null;
  status: "active" | "on_break" | "ended";
  total_minutes: number | null;
}

function formatElapsed(totalSeconds: number): string {
  const h = Math.floor(totalSeconds / 3600);
  const m = Math.floor((totalSeconds % 3600) / 60);
  const s = totalSeconds % 60;
  return [h, m, s].map((n) => String(n).padStart(2, "0")).join(":");
}

// Manual is the default and always-available method (bug C4): geo-fence is
// an optional secondary action for orgs that want it, never a requirement.
// A user with no location permission, no branch coordinates configured, or
// a non-geo browser must still be able to check in/out.
//
// Status (checked-in/on-break, red button, live timer) is read from
// /work-sessions/me/active rather than derived locally — that endpoint is
// the single source of truth shared with the desktop app (backend keeps
// AttendanceRecord and WorkSession in sync on either side, see
// app/services/attendance_sync.py), so a check-in from the desktop app
// shows up here automatically on the next poll, and vice versa.
export function CheckInWidget() {
  const qc = useQueryClient();
  const [locating, setLocating] = useState(false);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);

  const { data: session } = useQuery({
    queryKey: ["work-session", "active"],
    queryFn: async () => (await apiClient.get<ActiveWorkSession | null>("/work-sessions/me/active")).data,
    refetchInterval: 15000, // picks up a desktop check-in/out within ~15s
  });

  const isOnBreak = session?.status === "on_break";
  const isCheckedIn = !!session && (session.status === "active" || isOnBreak);

  useEffect(() => {
    if (!isCheckedIn || !session) {
      setElapsedSeconds(0);
      return;
    }
    const startedAt = new Date(session.started_at).getTime();
    const tick = (): void => setElapsedSeconds(Math.max(0, Math.floor((Date.now() - startedAt) / 1000)));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [isCheckedIn, session]);

  const checkIn = useMutation({
    mutationFn: (coords?: { latitude: number; longitude: number }) =>
      apiClient.post("/attendance/check-in", coords ? { method: "geo", ...coords } : { method: "manual" }),
    onSuccess: (res) => {
      const lateMin = res.data?.late_minutes ?? 0;
      toast.success(lateMin > 0 ? `Checked in — ${lateMin}m late` : "Checked in — on time");
      void qc.invalidateQueries({ queryKey: ["attendance"] });
      void qc.invalidateQueries({ queryKey: ["work-session"] });
    },
    onError: (err: unknown) => {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "Check-in failed";
      toast.error(msg);
    },
  });

  const checkOut = useMutation({
    mutationFn: () => apiClient.post("/attendance/check-out", {}),
    onSuccess: (res) => {
      const ot = res.data?.overtime_minutes ?? 0;
      toast.success(ot > 0 ? `Checked out — ${ot}m overtime` : "Checked out");
      void qc.invalidateQueries({ queryKey: ["attendance"] });
      void qc.invalidateQueries({ queryKey: ["work-session"] });
    },
    onError: (err: unknown) => {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "Check-out failed";
      toast.error(msg);
    },
  });

  function checkInWithLocation() {
    if (!navigator.geolocation) {
      toast.error("Geolocation isn't available in this browser — use manual check-in instead");
      return;
    }
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setLocating(false);
        checkIn.mutate({ latitude: pos.coords.latitude, longitude: pos.coords.longitude });
      },
      () => {
        setLocating(false);
        toast.error("Couldn't get your location — use manual check-in instead");
      },
      { enableHighAccuracy: true, timeout: 10000 },
    );
  }

  const busy = locating || checkIn.isPending || checkOut.isPending;

  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div
            className={`flex h-9 w-9 items-center justify-center rounded-lg ${
              isOnBreak ? "bg-amber-500" : isCheckedIn ? "bg-red-600" : "bg-[hsl(var(--primary))]"
            }`}
          >
            {isOnBreak ? <Coffee size={16} className="text-white" /> : <Clock size={16} className="text-white" />}
          </div>
          <div>
            <p className="text-sm font-semibold">Check-in / Check-out</p>
            {isCheckedIn ? (
              <p
                data-testid="timer-display"
                className={`font-mono text-sm font-semibold tabular-nums ${
                  isOnBreak ? "text-amber-500" : "text-[hsl(var(--foreground))]"
                }`}
              >
                {isOnBreak ? "On break — " : "Checked in — "}
                {formatElapsed(elapsedSeconds)}
              </p>
            ) : (
              <p className="text-xs text-[hsl(var(--foreground-muted))]">
                Manual check-in works anywhere — no location access needed.
              </p>
            )}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            disabled={busy}
            data-testid="checkin-button"
            onClick={() => void (isCheckedIn ? checkOut.mutate() : checkIn.mutate(undefined))}
            className={`flex items-center gap-2 rounded-md px-4 py-2 text-sm font-medium text-white disabled:opacity-60 ${
              isCheckedIn ? "bg-red-600 hover:bg-red-700" : "bg-[hsl(var(--primary))] hover:bg-[hsl(var(--primary-hover))]"
            }`}
          >
            {busy ? (
              <Loader2 size={14} className="animate-spin" />
            ) : isCheckedIn ? (
              <LogOut size={14} />
            ) : (
              <LogIn size={14} />
            )}
            {isCheckedIn ? "Check Out" : "Check In"}
          </button>
          {!isCheckedIn && (
            <button
              disabled={busy}
              onClick={checkInWithLocation}
              title="Optional: confirm you're within your branch's geo-fence radius"
              className="flex items-center gap-1.5 rounded-md px-2 py-2 text-xs font-medium text-[hsl(var(--foreground-muted))] hover:bg-[hsl(var(--accent))] disabled:opacity-60"
            >
              <MapPin size={13} />
              Use my location
            </button>
          )}
        </div>
      </div>
    </Card>
  );
}
