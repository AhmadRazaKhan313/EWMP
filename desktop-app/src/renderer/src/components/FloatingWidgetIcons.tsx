/**
 * The two icons used by the floating check-in / break widget. The paths are
 * the design's own (person + clock, coffee cup); they take their colour from
 * `currentColor` and their size from the surrounding `.fw-btn svg` rule.
 */
export function PersonClockIcon(): JSX.Element {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <circle cx="12" cy="8" r="4" stroke="currentColor" strokeWidth="1.8" />
      <path d="M5 20c0-3.5 3-6 7-6s7 2.5 7 6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      <circle cx="17.5" cy="6.5" r="3.2" stroke="currentColor" strokeWidth="1.6" />
      <path d="M17.5 5.2v1.5l1 0.7" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
    </svg>
  );
}

export function CoffeeCupIcon(): JSX.Element {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <path d="M6 9h11a2 2 0 0 1 2 2v1a4 4 0 0 1-4 4H9a4 4 0 0 1-4-4v-1a2 2 0 0 1 2-2z" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
      <path d="M18 11h1.5a2.5 2.5 0 0 1 0 5H18" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      <path d="M8 18h8" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      <path d="M10 6c0-1 1-2 2-2s2 1 2 2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      <path d="M13 4.5c0-0.8 0.7-1.5 1.5-1.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}
