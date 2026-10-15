/**
 * Design-system theme for Tailwind — IDENTICAL in frontend/ and desktop-app/
 * (a test in the frontend fails if they drift). Values live in the CSS
 * tokens (styles/globals.css, "SHARED TOKENS" block); this file only gives
 * them Tailwind class names so components can write `bg-primary`,
 * `text-gray-600`, `border-border`, `rounded-md`, `shadow-xs`,
 * `text-display-xs` instead of `bg-[hsl(var(--primary))]`.
 *
 * Names follow the Figma design (Untitled UI v7): radius md = 8px, etc.
 */
const scale = (name, steps) =>
  Object.fromEntries(steps.map((s) => [s, `hsl(var(--${name}-${s}) / <alpha-value>)`]));
const role = (name) => `hsl(var(--${name}) / <alpha-value>)`;

const FULL = [25, 50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950];
const STATUS = [50, 100, 300, 400, 500, 600, 700, 950];

module.exports = {
  colors: {
    brand: scale("brand", FULL),
    gray: scale("gray", FULL),
    error: scale("error", STATUS),
    warning: scale("warning", STATUS),
    success: scale("success", STATUS),
    blue: scale("blue", [50, 100, 400, 500, 600, 700, 950]),

    background: { DEFAULT: role("background"), subtle: role("background-subtle") },
    foreground: { DEFAULT: role("foreground"), subtle: role("foreground-subtle"), muted: role("foreground-muted") },
    card: { DEFAULT: role("card"), foreground: role("card-foreground") },
    primary: { DEFAULT: role("primary"), foreground: role("primary-foreground"), hover: role("primary-hover") },
    secondary: { DEFAULT: role("secondary"), foreground: role("secondary-foreground"), hover: role("secondary-hover") },
    accent: { DEFAULT: role("accent"), foreground: role("accent-foreground") },
    muted: { DEFAULT: role("muted"), foreground: role("muted-foreground") },
    destructive: { DEFAULT: role("destructive"), foreground: role("destructive-foreground"), subtle: role("destructive-subtle") },
    border: { DEFAULT: role("border"), strong: role("border-strong") },
    input: role("input"),
    ring: role("ring"),
  },
  borderRadius: {
    xs: "var(--radius-xs)",
    sm: "var(--radius-sm)",
    md: "var(--radius-md)",
    lg: "var(--radius-lg)",
    xl: "var(--radius-xl)",
    "2xl": "var(--radius-2xl)",
  },
  boxShadow: {
    xs: "var(--shadow-xs)",
    sm: "var(--shadow-sm)",
    md: "var(--shadow-md)",
    lg: "var(--shadow-lg)",
    xl: "var(--shadow-xl)",
    skeuo: "var(--shadow-skeuo)",
  },
  // [font-size, line-height] — the design's text and display styles
  fontSize: {
    xs: ["12px", "18px"],
    sm: ["14px", "20px"],
    base: ["16px", "24px"],
    lg: ["18px", "28px"],
    xl: ["20px", "30px"],
    "display-xs": ["24px", "32px"],
    "display-sm": ["30px", "38px"],
    "display-md": ["36px", "44px"],
    "display-lg": ["48px", "60px"],
  },
};
