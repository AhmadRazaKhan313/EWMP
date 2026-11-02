import { useEffect, useState } from "react";

/**
 * A real, live analog clock — not a static illustration. This is the
 * one deliberately bold element of the auth flow's brand panel (see
 * AuthShell), and it's literal rather than decorative on purpose: the
 * product's entire job is precise time accounting, so a dial that
 * actually ticks the current second is more honest than an abstract
 * gradient or icon-in-a-box would be.
 *
 * Respects prefers-reduced-motion by freezing the second hand (hour/
 * minute hands still reflect real time on mount, they just don't
 * animate between renders).
 */
export default function ClockMotif({ size = 280 }: { size?: number }): JSX.Element {
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduceMotion) return;

    const timer = setInterval(() => setNow(new Date()), 1000);
    return (): void => clearInterval(timer);
  }, []);

  const seconds = now.getSeconds();
  const minutes = now.getMinutes() + seconds / 60;
  const hours = (now.getHours() % 12) + minutes / 60;

  const secondDeg = seconds * 6;
  const minuteDeg = minutes * 6;
  const hourDeg = hours * 30;

  const center = 100;
  const radius = 92;

  const ticks = Array.from({ length: 12 }, (_, i) => {
    const angle = (i * 30 * Math.PI) / 180;
    const isCardinal = i % 3 === 0;
    const outer = radius - 4;
    const inner = outer - (isCardinal ? 12 : 6);
    return {
      x1: center + inner * Math.sin(angle),
      y1: center - inner * Math.cos(angle),
      x2: center + outer * Math.sin(angle),
      y2: center - outer * Math.cos(angle),
      isCardinal,
    };
  });

  return (
    <svg
      viewBox="0 0 200 200"
      width={size}
      height={size}
      role="img"
      aria-label="A live clock"
      className="text-[hsl(var(--auth-accent))]"
    >
      <circle cx={center} cy={center} r={radius} fill="none" stroke="currentColor" strokeOpacity={0.35} strokeWidth={1.5} />
      {ticks.map((t, i) => (
        <line
          key={i}
          x1={t.x1}
          y1={t.y1}
          x2={t.x2}
          y2={t.y2}
          stroke="currentColor"
          strokeOpacity={t.isCardinal ? 0.9 : 0.4}
          strokeWidth={t.isCardinal ? 2 : 1}
          strokeLinecap="round"
        />
      ))}
      {/* Hour hand */}
      <line
        x1={center}
        y1={center}
        x2={center}
        y2={center - radius * 0.48}
        stroke="white"
        strokeWidth={4}
        strokeLinecap="round"
        transform={`rotate(${hourDeg} ${center} ${center})`}
      />
      {/* Minute hand */}
      <line
        x1={center}
        y1={center}
        x2={center}
        y2={center - radius * 0.72}
        stroke="white"
        strokeWidth={3}
        strokeLinecap="round"
        transform={`rotate(${minuteDeg} ${center} ${center})`}
      />
      {/* Second hand — the accent, the only moving color against the dial */}
      <line
        x1={center}
        y1={center + radius * 0.18}
        x2={center}
        y2={center - radius * 0.82}
        stroke="currentColor"
        strokeWidth={1.5}
        strokeLinecap="round"
        transform={`rotate(${secondDeg} ${center} ${center})`}
        style={{ transition: "transform 0.2s cubic-bezier(0.4, 2.2, 0.6, 1)" }}
      />
      <circle cx={center} cy={center} r={4} fill="currentColor" />
    </svg>
  );
}
