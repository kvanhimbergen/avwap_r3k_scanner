# Design.md — Atlas Frontend Design System

> Complete specification for rebuilding the Atlas dark-mode trading dashboard UI.
> Feed this file to any project to reproduce the exact look and feel.

---

## Table of Contents

1. [Tech Stack & Dependencies](#1-tech-stack--dependencies)
2. [Color System](#2-color-system)
3. [Typography](#3-typography)
4. [Global Styles](#4-global-styles)
5. [Layout Shell](#5-layout-shell)
6. [Component Library](#6-component-library)
7. [Data Visualization](#7-data-visualization)
8. [Page Blueprints](#8-page-blueprints)
9. [Animation & Transitions](#9-animation--transitions)
10. [Icons](#10-icons)
11. [Spacing & Sizing Conventions](#11-spacing--sizing-conventions)
12. [Utility Patterns](#12-utility-patterns)
13. [Formatters](#13-formatters)

---

## 1. Tech Stack & Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| **react** | 19.x | UI framework |
| **react-dom** | 19.x | DOM renderer |
| **react-router-dom** | 7.x | Client-side routing |
| **recharts** | 3.x | Charting (Area, Bar, Pie, Line) |
| **zustand** | 5.x | Lightweight state management |
| **axios** | 1.x | HTTP client with interceptor |
| **lucide-react** | 0.575+ | Icon library (~300 icons) |
| **date-fns** | 4.x | Date formatting |
| **tailwindcss** | 4.x | Utility-first CSS framework |
| **vite** | 7.x | Build tool + dev server |
| **@vitejs/plugin-react** | latest | React fast refresh |
| **@tailwindcss/vite** | latest | Tailwind v4 Vite integration |

### Vite Config

```js
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 3002,
    strictPort: true,
    proxy: {
      '/api': 'http://localhost:8000',
      '/ws': { target: 'ws://localhost:8000', ws: true },
    },
  },
})
```

---

## 2. Color System

### 2.1 Core Tokens (Tailwind `@theme`)

Defined in `index.css` using Tailwind v4's `@theme` directive. These become utility classes like `bg-atlas-bg`, `text-atlas-green`, `border-atlas-border`, etc.

```css
@import "tailwindcss";

@theme {
  --color-atlas-bg: #0a0e17;
  --color-atlas-card: #111827;
  --color-atlas-border: #1f2937;
  --color-atlas-text: #e5e7eb;
  --color-atlas-muted: #9ca3af;
  --color-atlas-green: #10b981;
  --color-atlas-red: #ef4444;
  --color-atlas-amber: #f59e0b;
  --color-atlas-blue: #3b82f6;
}
```

| Token | Hex | Role |
|-------|-----|------|
| `atlas-bg` | `#0a0e17` | Page background — deep navy-black |
| `atlas-card` | `#111827` | Card/panel surfaces (gray-900) |
| `atlas-border` | `#1f2937` | All borders, dividers, scrollbar thumb (gray-800) |
| `atlas-text` | `#e5e7eb` | Primary text (gray-200) |
| `atlas-muted` | `#9ca3af` | Secondary/label text (gray-400) |
| `atlas-green` | `#10b981` | Positive P&L, active states, success (emerald-500) |
| `atlas-red` | `#ef4444` | Negative P&L, errors, danger (red-500) |
| `atlas-amber` | `#f59e0b` | Warnings, paper-mode indicator (amber-500) |
| `atlas-blue` | `#3b82f6` | Primary actions, links, info, logo accent (blue-500) |

### 2.2 Extended Palette (Used via Tailwind defaults, not custom tokens)

| Color | Hex | Context |
|-------|-----|---------|
| Purple | `#a78bfa` / `purple-400/500` | AI/Brain features, Lab, Claude co-pilot |
| Pink | `#f472b6` / `#ec4899` | Charity/donations, accent |
| Cyan | `#06b6d4` | Options/wheel strategy, evaluating status |
| Lime | `#84cc16` | Vol crush strategy |
| Teal | `#14b8a6` | Sector rotation strategy |
| Orange | `#f97316` | Leveraged options strategy |
| Violet | `#8b5cf6` | Volatility harvest strategy |

### 2.3 Semantic Color Usage

- **P&L positive:** `text-atlas-green`, `bg-atlas-green/[0.03]` (row tint), `bg-atlas-green/15` (badge)
- **P&L negative:** `text-atlas-red`, `bg-atlas-red/[0.03]` (row tint), `bg-atlas-red/15` (badge)
- **P&L neutral:** `text-atlas-muted`
- **Active/enabled:** `bg-atlas-green/15 text-atlas-green`
- **Disabled/off:** `bg-atlas-muted/10 text-atlas-muted`
- **Warning:** `bg-atlas-amber/15 text-atlas-amber`
- **Error/critical:** `bg-atlas-red/15 text-atlas-red`
- **Info:** `bg-atlas-blue/15 text-atlas-blue`
- **AI/brain:** `bg-purple-500/20 text-purple-400`

---

## 3. Typography

### 3.1 Font Families

Loaded via Google Fonts in `index.html`:

```html
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
```

| Font | Usage | CSS |
|------|-------|-----|
| **DM Sans** (400, 500, 600, 700) | All UI text — labels, headings, nav, buttons | `font-family: "DM Sans", system-ui, -apple-system, sans-serif` |
| **JetBrains Mono** (400, 500, 600) | All numerical data — prices, percentages, timestamps, table cells | `font-family: "JetBrains Mono", ui-monospace, monospace` (via `font-mono`) |

Applied in CSS:

```css
body {
  font-family: "DM Sans", system-ui, -apple-system, sans-serif;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}
```

### 3.2 Type Scale

| Size | Tailwind | Usage |
|------|----------|-------|
| 30px | `text-3xl` | Hero stat (e.g., lifetime donation total) |
| 24px | `text-2xl` | Stat card values, summary numbers |
| 20px | `text-xl` | Page titles, regime labels, large counts |
| 18px | `text-lg` | Gauge center values, detail panel metrics |
| 16px | `text-base` | Logo, detail panel headers |
| 14px | `text-sm` | Nav items, card titles, section headers, body text |
| 12px | `text-xs` | Table cells, most body content, button labels |
| 11px | `text-[11px]` | Descriptions, filter labels, time range buttons |
| 10px | `text-[10px]` | Sub-labels, badge text, uppercase tracking labels |
| 9px | `text-[9px]` | Tiny badges, indicator values, footnotes |
| 8px | `text-[8px]` | Micro labels (e.g., "HARD" on circuit breakers) |

### 3.3 Common Type Combos

```
Stat value:        font-mono text-2xl font-bold
Card title:        text-sm font-semibold
Section label:     text-[10px] text-atlas-muted uppercase tracking-wide mb-2
Uppercase label:   text-[11px] text-atlas-muted uppercase tracking-wide
Monospace data:    font-mono text-xs font-semibold
Table header:      text-atlas-muted font-medium text-xs
Body text:         text-xs text-atlas-muted
```

---

## 4. Global Styles

### 4.1 Base Styles (`index.css`)

```css
@import "tailwindcss";

@theme {
  --color-atlas-bg: #0a0e17;
  --color-atlas-card: #111827;
  --color-atlas-border: #1f2937;
  --color-atlas-text: #e5e7eb;
  --color-atlas-muted: #9ca3af;
  --color-atlas-green: #10b981;
  --color-atlas-red: #ef4444;
  --color-atlas-amber: #f59e0b;
  --color-atlas-blue: #3b82f6;
}

body {
  font-family: "DM Sans", system-ui, -apple-system, sans-serif;
  background-color: #0a0e17;
  color: #e5e7eb;
  margin: 0;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

* {
  scrollbar-width: thin;
  scrollbar-color: #1f2937 transparent;
}

::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: #1f2937; border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: #374151; }

@keyframes slide-in {
  from { transform: translateX(100%); opacity: 0; }
  to { transform: translateX(0); opacity: 1; }
}

.animate-slide-in {
  animation: slide-in 0.2s ease-out;
}
```

### 4.2 Theme Notes

- **Dark-only** — no light mode, no theme toggle. Every component assumes dark background.
- Thin custom scrollbars match the border color.
- Anti-aliased text rendering on all platforms.

---

## 5. Layout Shell

### 5.1 App Structure

```
+--------+-----------------------------------------------+
| Sidebar|  Header Bar (h-12)                            |
| w-56   |  [Equity] | [Day P&L] | [Total P&L]  [Mode] |
|        |-----------------------------------------------|
| Logo   |                                               |
| Nav    |  Main Content Area                            |
| Links  |  (flex-1, overflow-y-auto, p-5)               |
|        |  <Outlet />                                   |
|        |                                               |
| Status |                                               |
+--------+-----------------------------------------------+
```

### 5.2 CSS Structure

```jsx
{/* Root */}
<div className="flex h-screen bg-atlas-bg text-atlas-text overflow-hidden">

  {/* Sidebar */}
  <aside className="w-56 shrink-0 border-r border-atlas-border flex flex-col bg-atlas-bg">
    {/* Logo area */}
    <div className="h-12 flex items-center px-5 border-b border-atlas-border">
      <span className="text-base font-bold tracking-tight">
        <span className="text-atlas-blue">A</span>TLAS
      </span>
    </div>

    {/* Navigation */}
    <nav className="flex-1 py-3 px-3 space-y-0.5">
      {/* NavLink items */}
    </nav>

    {/* Connection status */}
    <div className="border-t border-atlas-border px-4 py-3">
      {/* Status dot + label */}
    </div>
  </aside>

  {/* Main area */}
  <div className="flex-1 flex flex-col min-w-0">
    {/* Header */}
    <header className="h-12 shrink-0 border-b border-atlas-border flex items-center justify-between px-5 bg-atlas-bg">
      {/* Left: metrics with dividers */}
      {/* Right: regime badge + mode badge */}
    </header>

    {/* Page content */}
    <main className="flex-1 overflow-y-auto p-5">
      <Outlet />
    </main>
  </div>
</div>
```

### 5.3 Sidebar Navigation Item

```jsx
<NavLink
  to={path}
  className={({ isActive }) =>
    `flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors ${
      isActive
        ? 'bg-atlas-card text-atlas-text font-medium'
        : 'text-atlas-muted hover:text-atlas-text hover:bg-atlas-card/50'
    }`
  }
>
  <Icon size={16} strokeWidth={1.75} />
  {label}
</NavLink>
```

### 5.4 Header Metrics

Left side — three metrics separated by vertical dividers:

```jsx
<div className="flex items-center gap-4">
  {/* Metric block */}
  <div>
    <p className="text-[11px] text-atlas-muted uppercase tracking-wide">Equity</p>
    <p className="font-mono text-sm font-semibold">$25,432.10</p>
  </div>

  {/* Vertical divider */}
  <div className="w-px h-5 bg-atlas-border" />

  {/* Next metric... */}
</div>
```

Right side — regime badge + mode badge (see Badges section).

### 5.5 Content Width

Most pages use a max-width wrapper for readability:

```jsx
{/* Standard pages */}
<div className="p-6 space-y-4 max-w-[1600px] mx-auto">

{/* Narrower pages (Charity, Settings) */}
<div className="space-y-6 max-w-[1200px] mx-auto">

{/* Dashboard uses full width */}
<div className="space-y-4 h-full">
```

---

## 6. Component Library

### 6.1 Card

The universal container:

```jsx
{/* Standard card */}
<div className="bg-atlas-card border border-atlas-border rounded-lg p-4">

{/* Card with colored left border */}
<div className="bg-atlas-card border border-atlas-border rounded-lg p-4 border-l-2"
     style={{ borderLeftColor: strategyColor }}>

{/* Selected card */}
<div className="bg-atlas-card border border-atlas-blue ring-1 ring-atlas-blue/30 rounded-lg p-4">

{/* Danger card */}
<div className="bg-atlas-card border border-atlas-red/40 rounded-lg">

{/* Full-height scrollable card */}
<div className="bg-atlas-card border border-atlas-border rounded-lg p-4 h-full flex flex-col">
  <h3 className="text-sm font-semibold mb-3">{title}</h3>
  <div className="flex-1 overflow-y-auto min-h-0">
    {/* scrollable content */}
  </div>
</div>
```

### 6.2 Stat Card

Top-level metric display:

```jsx
<div className="bg-atlas-card border border-atlas-border rounded-lg p-4 min-w-0">
  <p className="text-[11px] text-atlas-muted uppercase tracking-wide mb-1">
    {label}
  </p>
  <p className={`font-mono text-2xl font-bold ${pnlColor(value)}`}>
    {formatCurrency(value)}
  </p>
</div>
```

### 6.3 Badges

**Status badge:**
```jsx
<span className="text-[10px] px-1.5 py-0.5 rounded font-bold bg-atlas-green/15 text-atlas-green">
  ACTIVE
</span>
```

Status → color mapping:
| Status | Background | Text |
|--------|-----------|------|
| Active/Enabled | `bg-atlas-green/15` | `text-atlas-green` |
| Disabled/Off | `bg-atlas-muted/10` | `text-atlas-muted` |
| Warning/Caution | `bg-atlas-amber/15` | `text-atlas-amber` |
| Error/Critical | `bg-atlas-red/15` | `text-atlas-red` |
| Info | `bg-atlas-blue/15` | `text-atlas-blue` |
| AI/Brain | `bg-purple-500/20` | `text-purple-400` |
| Evaluating | `bg-cyan-500/20` | `text-cyan-400` |

**Mode badge (PAPER/LIVE):**
```jsx
<span className="px-2 py-0.5 rounded text-[10px] font-semibold tracking-wider uppercase border border-atlas-amber/30 bg-atlas-amber/10 text-atlas-amber">
  PAPER
</span>
```

**Count badge (filter tabs):**
```jsx
<span className="text-[9px] px-1 py-0.5 rounded-full font-mono bg-atlas-border text-atlas-muted">
  42
</span>
```

**Regime badge (dynamic color via inline style):**
```jsx
<span className="text-[10px] font-semibold tracking-wider uppercase px-2 py-0.5 rounded"
  style={{
    backgroundColor: `${regimeColor}15`,
    color: regimeColor,
  }}>
  TRENDING UP
</span>
```

### 6.4 Tables

```jsx
<table className="w-full text-xs">
  <thead>
    <tr className="border-b border-atlas-border">
      <th className="py-2 px-2 text-left text-atlas-muted font-medium whitespace-nowrap">
        Column
      </th>
      {/* Sortable header */}
      <th className="py-2 px-2 text-left text-atlas-muted font-medium whitespace-nowrap cursor-pointer hover:text-atlas-text select-none transition-colors"
          onClick={handleSort}>
        Column {sortDir === 'asc' ? '\u25B4' : '\u25BE'}
      </th>
    </tr>
  </thead>
  <tbody>
    <tr className={`border-b border-atlas-border/50 ${
      pnl > 0 ? 'bg-atlas-green/[0.03] hover:bg-atlas-green/[0.05]'
              : 'bg-atlas-red/[0.03] hover:bg-atlas-red/[0.05]'
    }`}>
      <td className="py-2 px-2 font-mono">{value}</td>
    </tr>
  </tbody>
</table>

{/* Empty state */}
<tr>
  <td colSpan={columns} className="py-8 text-center text-atlas-muted">
    No data available
  </td>
</tr>
```

### 6.5 Buttons

**Primary (blue):**
```jsx
<button className="w-full rounded-lg bg-atlas-blue px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-atlas-blue/80 disabled:opacity-50 disabled:cursor-not-allowed">
  Submit
</button>
```

**Secondary (outline):**
```jsx
<button className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-atlas-card border border-atlas-border rounded-lg hover:border-atlas-blue/50 transition-colors text-atlas-text">
  <Icon size={12} /> Action
</button>
```

**Filter pill:**
```jsx
<button className={`px-2 py-0.5 rounded text-[11px] font-medium transition-colors ${
  active
    ? 'bg-atlas-border text-atlas-text'
    : 'text-atlas-muted hover:text-atlas-text'
}`}>
  Filter
</button>
```

**AI/Purple:**
```jsx
<button className="text-xs px-3 py-1.5 rounded bg-purple-500/20 text-purple-400 hover:bg-purple-500/30 transition-colors">
  Ask AI
</button>
```

**Danger:**
```jsx
<button className="text-xs px-4 py-2 rounded bg-atlas-red text-white hover:bg-red-600 transition-colors font-bold">
  Emergency Stop
</button>
```

### 6.6 Form Inputs

```jsx
{/* Standard input */}
<input className="w-full bg-atlas-bg border border-atlas-border rounded px-2 py-1.5 text-xs font-mono text-atlas-text focus:outline-none focus:border-atlas-blue/50" />

{/* Login input (larger) */}
<input className="w-full rounded-lg border border-atlas-border bg-atlas-bg px-4 py-2.5 text-sm text-atlas-text placeholder-atlas-muted focus:border-atlas-blue focus:outline-none" />

{/* Select dropdown */}
<select className="bg-atlas-bg border border-atlas-border rounded px-2.5 py-1.5 text-xs text-atlas-text focus:outline-none focus:border-atlas-blue/50 appearance-none cursor-pointer pr-6">
```

### 6.7 Skeleton Loader

```jsx
function Skeleton({ className = '' }) {
  return <div className={`animate-pulse rounded bg-atlas-border/50 ${className}`} />
}

{/* Usage examples */}
<Skeleton className="h-3 w-20" />     {/* Text line */}
<Skeleton className="h-7 w-32" />     {/* Stat value */}
<Skeleton className="h-[280px] w-full" /> {/* Chart area */}
```

### 6.8 Toast Notifications

```jsx
{/* Container */}
<div className="fixed top-4 right-4 z-[100] flex flex-col gap-2">

{/* Individual toast */}
<div className={`flex items-start gap-3 px-4 py-3 rounded-lg border shadow-lg backdrop-blur-sm max-w-sm animate-slide-in ${bgClass}`}>
  <Icon size={16} className="shrink-0 mt-0.5" />
  <div className="flex-1">
    <p className="text-sm font-medium">{title}</p>
    <p className="text-xs opacity-80 mt-0.5">{message}</p>
  </div>
  <button className="text-white/60 hover:text-white">
    <X size={14} />
  </button>
</div>
```

Toast type backgrounds:
| Type | Background | Border |
|------|-----------|--------|
| Error | `bg-red-900/90` | `border-red-500/40` |
| Warning | `bg-amber-900/90` | `border-amber-500/40` |
| Success | `bg-green-900/90` | `border-green-500/40` |
| Info | `bg-blue-900/90` | `border-blue-500/40` |

Auto-dismiss: 5000ms. Max 5 visible.

### 6.9 Slide-out Detail Panel

```jsx
{/* Backdrop */}
<div className="fixed inset-0 bg-black/40 z-40" onClick={onClose} />

{/* Panel */}
<div className="fixed inset-y-0 right-0 w-[480px] bg-atlas-card border-l border-atlas-border z-50 flex flex-col shadow-2xl">
  {/* Header */}
  <div className="shrink-0 p-4 border-b border-atlas-border flex items-center justify-between">
    <h2 className="text-base font-semibold">{title}</h2>
    <button className="p-1 hover:bg-atlas-border rounded" onClick={onClose}>
      <X size={16} />
    </button>
  </div>

  {/* Scrollable body */}
  <div className="flex-1 overflow-y-auto p-4 space-y-4">
    {/* content */}
  </div>

  {/* Pinned footer (e.g., AI chat) */}
  <div className="shrink-0 border-t border-atlas-border p-3">
    {/* chat input */}
  </div>
</div>
```

### 6.10 Confirmation Dialog

```jsx
<div className={`mt-4 p-4 rounded-lg border ${
  danger ? 'bg-atlas-red/10 border-atlas-red/30' : 'bg-atlas-green/10 border-atlas-green/30'
}`}>
  <div className="flex items-start gap-3">
    <AlertTriangle size={20} className="text-atlas-red shrink-0 mt-0.5" />
    <div className="flex-1">
      <h4 className="text-sm font-bold mb-1">{title}</h4>
      <p className="text-xs text-atlas-muted mb-3">{description}</p>
      <div className="flex items-center gap-2">
        <button className="text-xs px-4 py-2 rounded bg-atlas-red text-white hover:bg-red-600 font-bold">
          Confirm
        </button>
        <button className="text-xs px-4 py-2 rounded bg-atlas-border text-atlas-muted hover:text-atlas-text">
          Cancel
        </button>
      </div>
    </div>
  </div>
</div>
```

### 6.11 Section Container (Settings style)

```jsx
<div className={`bg-atlas-card border rounded-lg ${
  danger ? 'border-atlas-red/40' : 'border-atlas-border'
}`}>
  {/* Section header */}
  <div className={`p-4 border-b ${danger ? 'border-atlas-red/20' : 'border-atlas-border'}`}>
    <h3 className="text-sm font-semibold flex items-center gap-2">
      <Icon size={16} className={iconColor} />
      {title}
    </h3>
  </div>
  {/* Section body */}
  <div className="p-4">
    {children}
  </div>
</div>
```

### 6.12 Progress Bar

```jsx
<div className="h-1.5 bg-atlas-border rounded-full overflow-hidden">
  <div
    className="h-full rounded-full transition-all duration-500"
    style={{ width: `${percent}%`, backgroundColor: color, opacity: 0.8 }}
  />
</div>
```

Heights: `h-1` (tiny), `h-1.5` (standard), `h-2` (medium), `h-3` (large).

### 6.13 Connection Status Dot

```jsx
<span className="relative flex h-2.5 w-2.5">
  {connected && (
    <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-atlas-green opacity-40" />
  )}
  <span className={`relative inline-flex h-2.5 w-2.5 rounded-full ${
    connected ? 'bg-atlas-green' : 'bg-atlas-red'
  }`} />
</span>
```

### 6.14 AI Chat Interface

Pinned at bottom of detail panels:

```jsx
<div className="shrink-0 border-t border-atlas-border p-3">
  {/* Header */}
  <div className="flex items-center gap-1.5 mb-2">
    <MessageCircle size={12} className="text-purple-400" />
    <span className="text-[10px] text-purple-400 font-medium">Ask AI About This</span>
  </div>

  {/* Message history */}
  <div className="space-y-2 mb-2 max-h-32 overflow-y-auto">
    {/* User message */}
    <div>
      <span className="text-[9px] text-purple-400 uppercase tracking-wide">You</span>
      <p className="text-xs text-atlas-text font-medium">{message}</p>
    </div>
    {/* AI response */}
    <div className="text-xs text-atlas-muted bg-atlas-bg rounded p-2 border border-atlas-border/50">
      {response}
    </div>
  </div>

  {/* Input */}
  <div className="flex gap-2">
    <input className="flex-1 bg-atlas-bg border border-atlas-border rounded px-3 py-1.5 text-xs focus:border-purple-500/50 focus:outline-none" />
    <button className="p-1.5 rounded bg-purple-500/20 text-purple-400 hover:bg-purple-500/30 disabled:opacity-40">
      <Send size={12} />
    </button>
  </div>
</div>
```

---

## 7. Data Visualization

### 7.1 Global Chart Conventions

All charts use Recharts with these shared patterns:

**Container:**
```jsx
<ResponsiveContainer width="100%" height="100%">
  {/* or height={280} for fixed-height charts */}
```

**Tooltip:**
```jsx
<Tooltip
  contentStyle={{
    backgroundColor: '#111827',
    border: '1px solid #1f2937',
    borderRadius: 6,
    fontSize: 12,
  }}
/>
```

**Axes:**
```jsx
<XAxis
  axisLine={false}
  tickLine={false}
  tick={{ fontSize: 10, fill: '#9ca3af' }}
/>
<YAxis
  axisLine={false}
  tickLine={false}
  tick={{ fontSize: 10, fill: '#9ca3af' }}
/>
```

### 7.2 Area Chart (Equity Curves)

```jsx
<AreaChart data={data}>
  <defs>
    <linearGradient id="equityGrad" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stopColor="#10b981" stopOpacity={0.3} />
      <stop offset="100%" stopColor="#10b981" stopOpacity={0} />
    </linearGradient>
  </defs>
  <XAxis ... />
  <YAxis ... />
  <Tooltip ... />
  <ReferenceLine y={startEquity} stroke="#1f2937" strokeDasharray="4 4" />
  <Area
    type="monotone"
    dataKey="equity"
    stroke="#10b981"
    strokeWidth={2}
    fill="url(#equityGrad)"
    activeDot={{ r: 3, fill: '#10b981' }}
  />
</AreaChart>
```

Color is `#10b981` (green) when up, `#ef4444` (red) when down — determined dynamically.

### 7.3 Stacked Area Chart (Allocation Timeline)

```jsx
<AreaChart data={data}>
  {strategies.map(s => (
    <Area
      key={s}
      type="monotone"
      dataKey={s}
      stackId="1"
      stroke={strategyColor}
      fill={strategyColor}
      fillOpacity={0.6}
    />
  ))}
</AreaChart>
```

### 7.4 Bar Chart (P&L Distribution)

```jsx
<BarChart data={data}>
  <Bar dataKey="count" radius={[2, 2, 0, 0]} barSize={20}>
    {data.map((entry, i) => (
      <Cell key={i} fill={entry.range < 0 ? '#ef4444' : '#10b981'} />
    ))}
  </Bar>
</BarChart>
```

### 7.5 Bar Chart (Horizontal Exposure)

```jsx
<BarChart layout="vertical" data={data}>
  <XAxis type="number" ... />
  <YAxis type="category" dataKey="name" ... />
  <Bar dataKey="value" radius={[0, 4, 4, 0]} barSize={16}>
    {data.map((entry, i) => (
      <Cell key={i} fill={entry.color} />
    ))}
  </Bar>
</BarChart>
```

### 7.6 Pie Chart (Donut — Allocation)

```jsx
<PieChart>
  <Pie
    data={data}
    cx="50%"
    cy="50%"
    innerRadius={50}
    outerRadius={80}
    paddingAngle={2}
    dataKey="value"
    strokeWidth={0}
  >
    {data.map((entry, i) => (
      <Cell key={i} fill={entry.color} />
    ))}
  </Pie>
  <Tooltip ... />
</PieChart>

{/* Legend */}
<div className="flex flex-wrap gap-x-4 gap-y-1">
  <div className="flex items-center gap-1.5">
    <div className="w-2.5 h-2.5 rounded-sm" style={{ backgroundColor: color }} />
    <span className="text-[11px] text-atlas-muted">{label}</span>
    <span className="text-[11px] font-mono font-semibold">{pct}%</span>
  </div>
</div>
```

### 7.7 SVG Gauges

**Circular gauge (health scores):**
```jsx
<svg viewBox="0 0 100 100" className="w-16 h-16">
  {/* Track */}
  <circle cx="50" cy="50" r="35" fill="none" stroke="#1f2937" strokeWidth="8" />
  {/* Value arc */}
  <circle cx="50" cy="50" r="35" fill="none"
    stroke={scoreColor(value)}
    strokeWidth="8"
    strokeLinecap="round"
    strokeDasharray={`${(value / 100) * circumference} ${circumference}`}
    transform="rotate(-90 50 50)"
    className="transition-all duration-700"
  />
  {/* Center text */}
  <text x="50" y="50" textAnchor="middle" dominantBaseline="central"
    fill={scoreColor(value)} fontSize="22" fontWeight="bold"
    fontFamily="JetBrains Mono">
    {value}
  </text>
</svg>
```

**Arc gauge (drawdown):**
- 270-degree arc sweep, SVG viewBox `0 0 128 104`
- Track: `#1f2937`, value arc with threshold-based color
- Threshold markers (amber/red dots) at specific angles
- Center text: `JetBrains Mono`, fontSize 24, bold

**Progress ring (charity):**
- SVG viewBox `0 0 140 140`, radius 56, strokeWidth 10
- Pink stroke `#f472b6`
- Center: percentage text

### 7.8 Correlation Heatmap

Table-based (not a chart):

```jsx
<table className="w-full">
  <tbody>
    {strategies.map(row => (
      <tr key={row}>
        {strategies.map(col => {
          const v = matrix[row][col]
          const bg = row === col
            ? '#1f2937'
            : v > 0
              ? `rgba(239, 68, 68, ${Math.abs(v) * 0.6})`   // red
              : `rgba(59, 130, 246, ${Math.abs(v) * 0.6})`   // blue
          return (
            <td key={col}
              className={`w-8 h-8 text-center text-[9px] font-mono ${
                Math.abs(v) > 0.6 ? 'ring-1 ring-atlas-amber' : ''
              }`}
              style={{ backgroundColor: bg }}>
              {v.toFixed(1)}
            </td>
          )
        })}
      </tr>
    ))}
  </tbody>
</table>
```

### 7.9 Strategy Color Map

Use this consistent color assignment for any strategy/category:

```js
const STRATEGY_COLORS = {
  momentum_breakout:   '#10b981', // emerald
  pairs_reversion:     '#3b82f6', // blue
  crypto_trend:        '#f59e0b', // amber
  volatility_harvest:  '#8b5cf6', // violet
  overnight_edge:      '#ec4899', // pink
  options_wheel:       '#06b6d4', // cyan
  options_leveraged:   '#f97316', // orange
  options_vol_crush:   '#84cc16', // lime
  sector_rotation:     '#14b8a6', // teal
  bear_market_defense: '#ef4444', // red
}
```

---

## 8. Page Blueprints

### 8.1 Dashboard (`/`)

```
Layout: space-y-4 h-full

Row 1: grid grid-cols-4 gap-4
  [Equity StatCard] [Day P&L StatCard] [Total P&L StatCard] [Charity StatCard]

Row 2: grid grid-cols-5 gap-4 (minHeight: 340px)
  [Equity Curve AreaChart — col-span-3] [Strategy Performance cards — col-span-2]

Row 3: grid grid-cols-2 gap-4 (minHeight: 280px)
  [Positions Table] [Recent Trades Feed]
```

### 8.2 Trades (`/trades`)

```
Layout: p-6 space-y-4 max-w-[1600px] mx-auto

[Header: icon + title + count badge + Export CSV button]
[Summary stats: grid grid-cols-4 gap-4 — Total Trades, Win Rate, Profit Factor, Avg Hold]
[Filters + Distribution: grid grid-cols-1 lg:grid-cols-3 gap-4]
  [FilterBar — lg:col-span-2] [P&L Distribution BarChart]
[Trade table with expandable rows]
[Pagination bar]
```

### 8.3 Strategies (`/strategies`)

```
Layout: p-6 space-y-4 max-w-[1600px] mx-auto

[Header: icon + title + active count + DateRangeFilter]
[Allocation PieChart (donut)]
[Strategy cards: grid grid-cols-1 lg:grid-cols-2 gap-4]
  Each card: colored left border, allocation bar, 3-col metrics grid,
             mini equity curve, expandable params/trades section
[Activity log (collapsible)]
[Detail panel: w-[480px] slide-out with full metrics, equity curve, AI chat]
```

### 8.4 Risk (`/risk`)

```
Layout: p-6 space-y-6 max-w-[1600px] mx-auto

[Header: ShieldAlert icon (green/red) + title + status badge + DateRangeFilter + leverage]
[Drawdown gauges: grid grid-cols-3 gap-4 — daily, weekly, total (SVG arc gauges)]
[Circuit breakers: card with grid grid-cols-2 lg:grid-cols-3 gap-3 + trigger history]
[Bottom: grid grid-cols-1 lg:grid-cols-2 gap-4 (minHeight: 380)]
  [Exposure Breakdown (horizontal BarChart)] [Risk Events Log]
```

### 8.5 Adaptive Brain (`/adaptive`)

```
Layout: p-6 space-y-6 max-w-[1600px] mx-auto

[Header: Brain icon (purple) + title + subtitle + DateRangeFilter]
[Regime banner: colored bg/border from regime, icon, confidence %, history bar]
[Strategy health: grid grid-cols-1 md:2 lg:3 xl:4 gap-4 — CircularGauge cards]
[Cluster utilization: progress bars per cluster]
[Charts: grid grid-cols-1 lg:grid-cols-2 gap-6]
  [Allocation stacked AreaChart] [Correlation Heatmap (table)]
[Advisor feed: card with filter tabs, review entries, trigger button]
```

### 8.6 Strategy Lab (`/lab`)

```
Layout: space-y-6 max-w-[1600px] mx-auto

[Header: FlaskConical icon (purple) + title + subtitle]
[Pipeline funnel: horizontal 5-stage bar + arrow connectors + summary stats]
[Filter tabs: horizontal buttons with count badges]
[Experiment cards: responsive grid — status badge, thesis, metrics, action buttons]
[Activity feed with "Trigger New Ideas" and "Suggest Idea" buttons]
[Detail panel: w-[480px] slide-out with experiment details, equity curve, AI chat]
```

### 8.7 Charity (`/charity`)

```
Layout: space-y-6 max-w-[1200px] mx-auto

Accent color: pink (pink-300, pink-400, pink-500)

[Header: Heart icon (filled, pink) + title + subtitle]
[Hero stat: gradient card bg-gradient-to-br from-pink-500/10 via-atlas-card to-atlas-card]
  Large donation amount in text-3xl font-mono font-bold
[grid grid-cols-1 lg:grid-cols-2 gap-6]
  [SVG Progress Ring (pink stroke) + Year Breakdown] [Impact Estimate cards]
[grid grid-cols-1 lg:grid-cols-2 gap-6]
  [Milestone Markers with progress bars] [Donation History table]
```

### 8.8 Settings (`/settings`)

```
Layout: space-y-6 max-w-[1200px] mx-auto

[Header: Settings icon + title + subtitle]
[Mode toggle section: PAPER/LIVE badge + confirmation dialog]
[grid grid-cols-1 lg:grid-cols-2 gap-6]
  [Risk Params (grid of inputs)] [Alert Settings + Connection Status + API Key Status]
[AI Co-Pilot section: cost grid, tier pie chart, tier toggles, recent calls table]
[System Logs: level filter tabs + log viewer]
[Danger Zone: red-bordered section with Emergency Stop + Reset buttons]
```

### 8.9 Login (`/login`)

```
Layout: min-h-screen flex items-center justify-center bg-atlas-bg

[Card: w-full max-w-sm rounded-xl border border-atlas-border bg-atlas-card p-8 shadow-2xl]
  [ShieldCheck icon in blue circle: h-12 w-12 rounded-full bg-atlas-blue/10]
  [Title: text-xl font-semibold]
  [Subtitle: text-sm text-atlas-muted]
  [Password input]
  [Error text: text-sm text-atlas-red]
  [Submit button: full-width, bg-atlas-blue]
```

---

## 9. Animation & Transitions

### 9.1 CSS Animations

| Animation | Usage | Definition |
|-----------|-------|------------|
| `animate-slide-in` | Toast notifications | `translateX(100%) -> 0, opacity 0 -> 1, 0.2s ease-out` |
| `animate-pulse` | Skeletons, status dots, crisis banner | Built-in Tailwind |
| `animate-ping` | Connection dot ring | Built-in Tailwind |
| `animate-spin` | Loading spinners (Loader2 icon) | Built-in Tailwind |

### 9.2 Transition Classes

| Class | Duration | Usage |
|-------|----------|-------|
| `transition-colors` | default (150ms) | All interactive elements (buttons, links, nav items) |
| `transition-all` | default | Progress bars, badges |
| `transition-all duration-500` | 500ms | Allocation bars, progress fills |
| `transition-all duration-700` | 700ms | SVG gauge arcs, progress rings |
| `transition-all duration-1000` | 1000ms | Charity progress ring/bar |
| `transition-transform` | default | Chevron rotation on expand/collapse |

### 9.3 Interactive States

- **Buttons:** `hover:bg-{color}/80` or `hover:bg-{color}/30` for ghost buttons
- **Links:** `hover:text-atlas-text` (from muted)
- **Cards:** No hover effect by default; selected state via `border-atlas-blue ring-1 ring-atlas-blue/30`
- **Table rows:** `hover:bg-atlas-green/[0.05]` or `hover:bg-atlas-red/[0.05]`
- **Disabled:** `disabled:opacity-50 disabled:cursor-not-allowed`

---

## 10. Icons

### 10.1 Library

**lucide-react** — lightweight, consistent stroke icons.

### 10.2 Size Scale

| Size | Context |
|------|---------|
| `size={24}` | Page header icons |
| `size={20}` | Confirmation dialog icons |
| `size={16}` | Section/card headers, nav items |
| `size={14}` | Inline with text |
| `size={12}` | Button icons, small inline |
| `size={10}` | Tiny indicators |
| `size={8}` | Micro indicators (breaker pulse) |

### 10.3 Stroke Width

- Default: `strokeWidth={2}` (Lucide default)
- Nav items: `strokeWidth={1.75}` (slightly thinner for polish)

### 10.4 Key Icons Used

| Icon | Context |
|------|---------|
| `LayoutDashboard` | Dashboard nav |
| `ArrowLeftRight` | Trades nav |
| `Layers` | Strategies nav |
| `ShieldAlert` | Risk nav/header |
| `Brain` | Adaptive Brain nav |
| `FlaskConical` | Strategy Lab nav |
| `Heart` | Charity nav |
| `Settings` | Settings nav |
| `ShieldCheck` | Login page |
| `TrendingUp/Down` | P&L direction |
| `Activity` | Regime icon |
| `AlertTriangle` | Warnings, errors |
| `X` | Close buttons |
| `ChevronDown/Right` | Expand/collapse |
| `Loader2` | Loading spinner (with `animate-spin`) |
| `Send` | AI chat send |
| `MessageCircle` | AI chat header |
| `Download` | Export button |
| `ToggleLeft/Right` | Toggle switches |
| `RefreshCw` | Refresh/retry |
| `Zap` | Circuit breaker |
| `Target` | Position targeting |

---

## 11. Spacing & Sizing Conventions

### 11.1 Page Padding

| Context | Padding |
|---------|---------|
| Layout main content | `p-5` |
| Individual page content | `p-6` |
| Cards | `p-4` (standard), `p-3` (compact), `p-5` (large sections) |

### 11.2 Grid Gaps

| Gap | Context |
|-----|---------|
| `gap-2` | Tight (filter pills, inline elements) |
| `gap-3` | Compact (circuit breaker cards) |
| `gap-4` | Standard (most grids) |
| `gap-6` | Spacious (page sections, large grids) |

### 11.3 Vertical Spacing

| Spacing | Context |
|---------|---------|
| `space-y-0.5` | Nav items |
| `space-y-2` | List items, compact stacks |
| `space-y-4` | Standard page sections |
| `space-y-6` | Large page sections |

### 11.4 Border Radius

| Radius | Context |
|--------|---------|
| `rounded` | Badges, inputs, small elements |
| `rounded-md` | Nav items |
| `rounded-lg` | Cards, buttons, panels |
| `rounded-xl` | Login card |
| `rounded-full` | Dots, pills, count badges |
| `rounded-sm` | Legend color swatches |

### 11.5 Content Max Widths

| Width | Pages |
|-------|-------|
| `max-w-[1600px]` | Trades, Strategies, Risk, Adaptive Brain, Lab |
| `max-w-[1200px]` | Charity, Settings |
| `max-w-sm` (~384px) | Login form, toast container |
| None (full width) | Dashboard |

---

## 12. Utility Patterns

### 12.1 P&L Color Helper

```js
function pnlColor(value) {
  if (value > 0) return 'text-atlas-green'
  if (value < 0) return 'text-atlas-red'
  return 'text-atlas-muted'
}
```

### 12.2 Score Color Helper

```js
function scoreColor(score) {
  if (score >= 70) return '#10b981' // green
  if (score >= 40) return '#f59e0b' // amber
  return '#ef4444'                  // red
}
```

### 12.3 Vertical Divider

```jsx
<div className="w-px h-5 bg-atlas-border" />
```

### 12.4 Horizontal Divider

```jsx
<div className="h-px bg-atlas-border" />
```

### 12.5 Empty State

```jsx
<div className="flex flex-col items-center justify-center py-12 text-atlas-muted">
  <Icon size={24} className="mb-2 opacity-40" />
  <p className="text-sm">No data available</p>
</div>
```

### 12.6 Error State

```jsx
<div className="flex flex-col items-center justify-center min-h-[400px] gap-4 text-gray-400">
  <div className="p-4 rounded-full bg-red-500/10">
    <AlertTriangle className="w-10 h-10 text-red-400" />
  </div>
  <h2 className="text-lg font-semibold text-white">Something went wrong</h2>
  <button className="mt-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white text-sm rounded-lg transition-colors">
    Try Again
  </button>
</div>
```

### 12.7 Text Truncation

```jsx
{/* Single line */}
<span className="truncate">{text}</span>

{/* Multi-line clamp */}
<p className="line-clamp-2">{text}</p>
```

---

## 13. Formatters

Standard formatting functions used across all pages:

```js
// Currency — "$1,234.56"
function formatCurrency(value, decimals = 2) {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(value)
}

// Percent — "+12.34%" (with sign prefix)
function formatPercent(value, decimals = 2) {
  const prefix = value > 0 ? '+' : ''
  return `${prefix}${value.toFixed(decimals)}%`
}

// Number — "1,234.56"
function formatNumber(value, decimals = 2) {
  return new Intl.NumberFormat('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(value)
}

// Date — "Feb 24, 2026"
function formatDate(dateStr) {
  return new Date(dateStr).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  })
}

// Time — "14:30:00 EST"
function formatTime(dateStr) {
  return new Date(dateStr).toLocaleTimeString('en-US', {
    hour12: false,
    timeZoneName: 'short',
  })
}
```

---

## Quick Reference Card

```
Background:     #0a0e17 (atlas-bg)
Card Surface:   #111827 (atlas-card)
Borders:        #1f2937 (atlas-border)
Primary Text:   #e5e7eb (atlas-text)
Muted Text:     #9ca3af (atlas-muted)
Positive:       #10b981 (atlas-green)
Negative:       #ef4444 (atlas-red)
Warning:        #f59e0b (atlas-amber)
Primary Action: #3b82f6 (atlas-blue)

UI Font:        DM Sans (400/500/600/700)
Data Font:      JetBrains Mono (400/500/600)
Icons:          lucide-react
Charts:         Recharts
State:          Zustand
Routing:        react-router-dom v7
CSS:            Tailwind v4 (dark-only)

Theme:          Dark-only, no light mode
Layout:         Fixed sidebar (w-56) + header (h-12) + scrollable content
Max width:      1600px (data pages), 1200px (settings/charity)
Card pattern:   bg-atlas-card border border-atlas-border rounded-lg p-4
Badge pattern:  text-[10px] px-1.5 py-0.5 rounded font-bold bg-{color}/15 text-{color}
```
