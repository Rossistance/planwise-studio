---
name: PlanWise
colors:
  background: '#F2F1EC'
  surface: '#FCFBF8'
  surface-variant: '#F7F6F1'
  on-surface: '#1A1D20'
  on-surface-muted: '#5C6470'
  on-surface-faint: '#8A8F94'
  outline: '#DEDCD3'
  outline-strong: '#B9B6AA'
  primary: '#C7420A'
  primary-hover: '#A83605'
  on-primary: '#FFFFFF'
  primary-container: '#F9E9DE'
  info: '#2F74B8'
  info-container: '#E6EEF6'
  success: '#1E7A46'
  success-container: '#E3F0E7'
  warning: '#8F5F00'
  warning-container: '#F6EDD8'
  error: '#C23A2E'
  error-container: '#F8E7E4'
  neutral: '#6B7178'
  neutral-container: '#ECEBE6'
typography:
  brand-mark:
    fontFamily: Bahnschrift
    fontSize: 18px
    fontWeight: '700'
    lineHeight: 22px
    letterSpacing: 0.06em
  heading-lg:
    fontFamily: Bahnschrift
    fontSize: 21px
    fontWeight: '600'
    lineHeight: 26px
    letterSpacing: 0.01em
  body-base:
    fontFamily: Segoe UI
    fontSize: 14.5px
    fontWeight: '400'
    lineHeight: 22px
    letterSpacing: '0'
  label-eyebrow:
    fontFamily: Cascadia Mono
    fontSize: 10.5px
    fontWeight: '600'
    lineHeight: 13px
    letterSpacing: 0.14em
  stamp:
    fontFamily: Bahnschrift
    fontSize: 11px
    fontWeight: '700'
    lineHeight: 14px
    letterSpacing: 0.1em
  mono-data:
    fontFamily: Cascadia Mono
    fontSize: 12.5px
    fontWeight: '400'
    lineHeight: 17px
    letterSpacing: '0'
rounded:
  DEFAULT: 4px
  badge: 3px
  pill: 999px
spacing:
  unit: 2px
  xs: 4px
  sm: 8px
  md: 14px
  lg: 18px
  xl: 28px
  gutter: 16px
  row-height: 24px
  topbar-height: 52px
---

## Brand & Style

PlanWise is a construction project-controls tool, and its design system reads
as **"field office, drawing-set precision"** — the visual language of a
drafting table, not a consumer app. It was ported wholesale from a companion
product, SiteScope (an internal decision, "D12"), so the two share one
vocabulary: vellum-paper surfaces, hairline rules, DIN-style engineering
lettering, title-block structure, a safety-orange accent, blueprint-blue for
links and informational states, and rubber-stamp-styled status badges. Dark
mode isn't an inverted afterthought — it's framed as **"the night-shift
trailer"**: same structure, same hierarchy, tuned for low light.

Nothing here is soft or glassy. Corners are nearly square (4px), surfaces are
flat, borders are thin and literal, and monospace type does the job of
annotation marks on a drawing set. The overall impression should be a
professional instrument used by people who have spent twenty years in
Microsoft Project and Excel — dense, precise, and legible, not airy or
decorative.

## Colors

The palette is anchored by a warm, paper-like neutral scale rather than pure
white/gray: **`background` (`#F2F1EC`)** is a dulled vellum tone, while
`surface` (`#FCFBF8`) and `surface-variant` (`#F7F6F1`) sit just above it for
cards, panels, and the top bar. Text and structure use `on-surface`
(`#1A1D20`, near-black) down through `on-surface-muted` and
`on-surface-faint` for secondary and tertiary text, with `outline` /
`outline-strong` hairlines doing the work most UIs give to shadows.

**`primary` (`#C7420A`, "safety orange")** is the single brand accent —
reserved for the active tab, the primary button, brand-mark lettering, focus
rings, and "you are here" indicators (current-day marker, active row). It is
never used decoratively. **`info` (`#2F74B8`, "blueprint blue")** covers
links and informational tags/badges — a direct reference to actual blueprint
ink. Functional states (`success`, `warning`, `error`, `neutral`) each pair a
saturated foreground with a soft, near-white container tint, used for status
chips, stamps, and badges.

In dark mode ("night-shift trailer"), surfaces invert to near-black
(`#191C1F` background, `#22262A` panel) and the accent shifts warmer/brighter
(`#F97435`) to stay visible against the dark ground; every functional color
gets a corresponding brighter foreground + darkened container pair rather
than a flat opacity flip.

## Typography

Two typefaces split the work cleanly. **Bahnschrift** (a DIN-style,
condensed-engineering face, falling back to Segoe UI Semibold) is the
"display"/structural voice: all headings, the brand mark, tab labels, button
labels, title-block values, and stamps. **Segoe UI** is the body/data voice —
inputs, paragraph text, table cells. **Cascadia Mono** is a third, load-bearing
voice unique to this system: it renders uppercase micro-labels ("eyebrows"),
chip text, table headers, mono data (job numbers, dates), and tags — the
"drawing-set annotation" register that shows up constantly throughout the UI.

Base body text is small and tight by web standards — 14.5px/1.55 — reflecting
an information-dense, desktop-first tool. Micro-labels and mono annotations
run 10–12.5px with heavy letter-spacing (0.05–0.14em) and uppercase casing,
which is what gives the interface its "stamped/labeled" character. Numeric
columns always use tabular-nums so figures align in a grid.

## Layout & Spacing

Content is centered in a **1220px max-width column** with fairly tight edge
padding (20–28px), not generous whitespace — this is a data tool, and screen
space goes to tables, grids, and the Gantt chart, not air. Spacing values
cluster on a loose ~2px grid (4, 8, 14, 18, 24, 28px) rather than a strict 8pt
system; the recurring **24px row height** in the Gantt/schedule view is the
one spacing value the whole grid+chart split-pane layout is built around
(both halves must share it exactly or bars stop lining up with rows).

Breakpoints: 460px (stacks two-column forms), 480px (single-column phone
layout), 720px (main mobile breakpoint — tables collapse into cards, inputs
jump to 16px to stop iOS auto-zoom, touch targets grow to 44px per Apple
HIG), 900px (the Gantt split-pane stacks vertically), 1100px (the two-week
look-ahead setup row stacks). `env(safe-area-inset-*)` padding is used
throughout so content clears the notch/home-indicator on installed
(PWA-style) app windows.

## Elevation & Depth

There is almost no elevation system — surfaces are flat, separated by
hairline borders (`outline`/`outline-strong`), not shadows. The one shadow
token, `shadow-pop` (`0 10px 40px rgba(20,22,24,.18)`, heavier in dark mode),
is reserved for floating/overlay content only: the search-results dropdown
and modal dialogs. A 2px surface + 4px accent double-ring is used for
keyboard focus everywhere instead of glow/blur effects.

## Shapes

Corner radius is uniformly small and squared-off: **4px** is the default for
buttons, inputs, panels, dialogs, and table containers — a "drafted," precise
feel rather than a soft one. Two exceptions: status **chips** and **stamps**
use full-pill (999px) or near-pill shapes for compact inline badges, and
small status dots/badges use an even tighter 3px radius.

## Components

### Buttons

`.btn`: 1px `outline-strong` border, `surface` background, 4px radius,
7px/14px padding, Bahnschrift 13.5px label with slight letter-spacing.
Primary variant fills solid `primary` with white text; danger variant uses
`error` text/border on transparent; a `.sm` variant tightens padding. Plain
`.link` buttons are just colored text (info-blue, or error for destructive)
with no border.

### Panels & Cards

`.panel`: bordered container (`outline`, 4px radius) with a `panel-head` /
`panel-body` split — the head carries a Bahnschrift title plus a lighter
subtitle. This is the default wrapper for any grouped content block.

### Title Block (signature element)

The `.titleblock` is the system's most distinctive component: a horizontal
strip of cells separated by hairline vertical rules, directly imitating an
engineering drawing's title block. Each cell pairs an eyebrow label with a
Bahnschrift value. On mobile it collapses to a stacked list of label/value
rows.

### Stamps & Badges

`.stamp`: an outlined (not filled), uppercase, bold Bahnschrift label in a
status color — literally styled like a rubber approval stamp (OK / WARN /
ERR / INFO / NEUTRAL). `.badge`: the filled counterpart — soft container
background + saturated text, used inline in tables and lists for the same
status vocabulary.

### Navigation (Topbar)

A single fixed-height (52px) sticky top bar: brand mark in uppercase
Bahnschrift with the accent color picking out part of the wordmark, a
central job-number search field, and status chips (pill-shaped, dot +
mono text) pushed to the right. On mobile it wraps to two rows and the
search field takes its own full-width line.

### Inputs & Forms

Fields pair a Cascadia Mono uppercase micro-label above a bordered input
(`outline-strong`, 4px radius, `surface` background). Inline/quick-add forms
sit in a shaded (`surface-variant`) strip attached to the top or bottom edge
of a panel. Editable table cells (`.ecell`) are borderless until hover/focus,
so a data grid reads as plain values until you interact with it.

### Tables

Dense, hairline-divided rows; headers are uppercase Cascadia Mono with wide
letter-spacing and support click-to-sort (▲/▼ glyphs). Numeric columns
right-align with tabular figures. On mobile, tables reflow into
bordered "cards" — each cell prints its own label via `data-label`, and empty
cells disappear rather than leaving blank space.

### Schedule / Gantt (domain-specific)

A Microsoft-Project-style split pane: an editable task grid on the left, a
synchronized Gantt chart on the right, sharing one vertical scroll and an
identical 24px row height across both halves. Summary rows render as
bracket shapes (not bars), critical-path items render in `error` red,
milestones as rotated accent diamonds, and today's date as a thin accent
line through the chart.

### Drawings Workspace (domain-specific)

A toolbar of round color swatches for markup tools, plus a canvas-based
annotation layer over a rendered PDF page — the one place circular shapes
appear in an otherwise square-cornered system.

## Design System Notes for Stitch Generation

### Language to use

Describe screens as "field office," "drafting table," "title block,"
"stamped status," "blueprint annotation" — avoid soft/consumer language like
"friendly," "rounded," "playful," or "glassmorphic." This is a dense,
professional, construction-industry tool.

### Color references

- **Safety Orange** (`#C7420A` / dark: `#F97435`) — the one brand accent:
  primary actions, active states, focus rings.
- **Blueprint Blue** (`#2F74B8` / dark: `#63A9E0`) — links, info badges.
- **Vellum** (`#F2F1EC` background / `#FCFBF8` surface) — the paper-like base.
- **Ink** (`#1A1D20`) — primary text, near-black not pure black.
- Functional trio: **Success** `#1E7A46`, **Warning** `#8F5F00`, **Error**
  `#C23A2E`, each with a soft near-white container tint.

### Component prompts

- "A title-block header strip with 3–4 hairline-divided cells, each showing
  an uppercase mono label over a bold Bahnschrift value, safety-orange
  accents, 4px corners, vellum-paper background."
- "A dense data table with uppercase mono sortable headers, tabular numeric
  columns, hairline row dividers, and an approval stamp badge (outlined,
  uppercase, colored border and text) in one column."
- "A sticky top bar with an uppercase engineering-style wordmark (orange
  accent on part of the name), a centered search field, and pill-shaped
  status chips with a colored status dot, on a warm off-white background."

### Incremental iteration

Keep radius at 4px and borders hairline-thin across any new screen — the
biggest way to break this system visually is to soften corners or add
drop-shadow elevation where a hairline border belongs instead.
