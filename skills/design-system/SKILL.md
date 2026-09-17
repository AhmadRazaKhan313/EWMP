---
name: design-system
description: EWMP's design tokens, color system, and component conventions (used by both frontend/ and desktop-app/). Use whenever writing or styling UI — pages, components, modals, badges, status indicators — to stay consistent instead of inventing new colors/spacing.
---

# EWMP Design System

Shared visual language across `frontend/` (admin web) and `desktop-app/`
(Electron). Tailwind + CSS custom properties (HSL triplets), light/dark
via a `.dark` class. Tokens are defined once in each app's global CSS
(`frontend/src/styles/globals.css` and the desktop-app equivalent) — keep
both in sync if you add a token.

## Core rule: never hardcode a color. Always use a token.

```tsx
// ✅ correct
<span className="bg-[hsl(var(--status-active-bg))] text-[hsl(var(--status-active-fg))]" />

// ❌ wrong — don't do this
<span className="bg-green-100 text-green-700" />
```

Tokens are HSL triplets (e.g. `--primary: 243 75% 59%`), consumed as
`hsl(var(--token))`.

## Token reference

**Surfaces / text**
`--background`, `--background-subtle`, `--foreground`,
`--foreground-subtle`, `--foreground-muted`

**Brand / interactive**
`--primary`, `--primary-foreground`, `--primary-hover`,
`--secondary`, `--secondary-foreground`, `--secondary-hover`,
`--accent`, `--accent-foreground`, `--ring`

**Muted / borders / inputs**
`--muted`, `--muted-foreground`, `--border`, `--border-strong`, `--input`

**Semantic (status, alerts, banners)**
`--destructive` / `--destructive-foreground`
`--success` / `--success-subtle`
`--warning` / `--warning-subtle`
`--info` / `--info-subtle`

**Status badges/pills specifically** (use these, not the generic semantic
ones, for entity status like "Active"/"Error"/"Pending")
`--status-active-bg` / `--status-active-fg`
`--status-error-bg` / `--status-error-fg`
`--status-warning-bg` / `--status-warning-fg`

**Sidebar (always dark, independent of light/dark mode)**
`--sidebar-background`, `--sidebar-foreground`, `--sidebar-muted`,
`--sidebar-active`, `--sidebar-hover`, `--sidebar-border`

**Shadows**
`--shadow-xs`, `--shadow-sm`, `--shadow-md`

## Fonts

`font-sans` (`--font-sans`), `font-heading` (`--font-heading`),
`font-mono` (`--font-mono`) — set in `tailwind.config.js`
`theme.extend.fontFamily`. Use these utility classes, not arbitrary
`font-family` values.

## Component conventions (`src/components/`)

Atomic-ish structure, not strict atomic design:

- **atoms/** (`index.tsx`) — smallest pure-presentation pieces, no
  business logic, no API calls. Existing ones: `Badge` (variants:
  default/success/warning/error/info/outline — maps to the status-*
  tokens above), `Skeleton` / `SkeletonTable` (loading states, use the
  `.skeleton` shimmer class already defined globally, don't reinvent
  loading UI), `StatusDot` (color: green/yellow/red/gray/blue, with
  optional `pulse` using `.status-dot-pulse`).
- **molecules/** — composed reusable pieces, e.g. `DataTable`. Reuse
  `DataTable` for any tabular admin list instead of hand-rolling a table.
- **organisms/** — feature-sized composed components (sidebar, topbar,
  drawers like `EmployeeDrawer`/`DeviceDrawer`/`AssetDrawer`,
  `RolesManager`). New "side-panel for viewing/editing one record"
  features should follow the existing `*Drawer.tsx` pattern.

Use the `cn()` helper (`src/utils/cn.ts`) for conditional/merged
className strings — don't concatenate class strings manually.

## When adding a new visual element

1. Reach for an existing atom/molecule/organism first.
2. If a new color is genuinely needed, add it as a token in both apps'
   global CSS (light **and** dark variants) rather than a one-off inline
   color.
3. Match existing spacing/radius/shadow scale — look at a sibling
   component rather than guessing values.
