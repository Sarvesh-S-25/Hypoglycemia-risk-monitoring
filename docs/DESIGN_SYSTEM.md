# GlucoSentry Design System

Derived from the reference recording (`ruul-a6e6a6.mp4`, the Ruul.io marketing site).
Colors below were sampled pixel-by-pixel from extracted video frames, so they are
exact, not approximations. **Any agent building UI must use these tokens and must not
invent new colors, radii, or font families.**

---

## 1. Design language in one paragraph

Warm off-white canvas. Content sits in large, generously padded cards with a ~24px
corner radius, separated by big whitespace gaps rather than borders. Cards come in
exactly three "surface personalities": **deep forest-green** (inverted, for the most
important panel), **warm neutral grey** (secondary), and **lime** (the single
attention-grabbing accent, used sparingly, at most once per screen). Inside a card,
data is presented on a floating **white inner panel** with a soft shadow, which reads
like a device screenshot embedded in the card. Headings are a transitional **serif**
at large sizes; everything functional (labels, buttons, table text) is a neutral
**sans**. Buttons are **pill-shaped**, either solid dark or solid white. Section
labels are tiny, uppercase, letter-spaced and numbered — the reference shows
`[03] EXCLUSIVE TO RUUL`, ours will read `[01] LIVE MONITORING`. A faint square grid
overlay appears on dark cards, and as a thin full-width divider band between sections.

## 2. Color tokens

```css
:root {
  /* Canvas */
  --gs-bg:             #FBFCF7;  /* page background, warm off-white */
  --gs-bg-alt:         #EFEFEA;  /* alternating full-bleed section band */

  /* Surfaces */
  --gs-surface-dark:   #1B2821;  /* deep forest green-black card */
  --gs-surface-dark-2: #27362F;  /* dark card, raised/inner region */
  --gs-surface-grey:   #EBECE6;  /* warm neutral card */
  --gs-surface-white:  #FFFFFF;  /* floating inner panel (the "device screen") */
  --gs-surface-inner:  #C8C9C3;  /* inset placeholder / disabled fill */

  /* Accent */
  --gs-lime:           #D0FF63;  /* THE accent. One per screen. */
  --gs-lime-ink:       #395E01;  /* text/icon on lime */
  --gs-lime-soft:      #DDFF92;  /* text highlight on dark surfaces */

  /* Ink */
  --gs-ink:            #14191A;  /* primary text on light */
  --gs-ink-muted:      #5C635F;  /* secondary text on light */
  --gs-ink-faint:      #9AA09B;  /* tertiary / axis labels */
  --gs-ink-invert:     #FAFBF5;  /* primary text on dark */
  --gs-ink-invert-mut: #A8B2AB;  /* secondary text on dark */

  /* Hairlines */
  --gs-line:           #DEDFD8;  /* dividers on light */
  --gs-line-dark:      #33423A;  /* dividers/grid on dark */
}
```

### 2.1 Semantic / clinical colors

The Ruul palette carries no status colors, so these are additions. They are kept
muted to stay inside the design language — **no saturated medical red or green**.

```css
:root {
  --gs-mode-eco:    #7E8C7F;  /* Eco     — calm sage */
  --gs-mode-normal: #2F6D4F;  /* Normal  — forest */
  --gs-mode-watch:  #B8862B;  /* Watch   — desaturated amber */
  --gs-mode-verify: #B2452F;  /* Verify  — desaturated terracotta */

  --gs-ok:          #2F6D4F;
  --gs-warn:        #B8862B;
  --gs-danger:      #B2452F;
  --gs-trace:       #1B2821;  /* ECG waveform stroke on white */
  --gs-trace-stale: #C8C9C3;  /* ECG stroke when SQI rejected / data stale */
}
```

**Mode color rule:** a mode color is used for a small dot plus the badge border only.
Never flood a whole card in a status color — that breaks the reference aesthetic.

### 2.2 Dark mode

Out of scope for the prototype: the reference is light-only and the dashboard is a
bench/demo instrument that will be shown on a projector. If it is added later, invert
by promoting `--gs-surface-dark` to the canvas; do **not** simply invert lightness.

## 3. Typography

```css
--gs-font-display: "Instrument Serif", "Newsreader", Georgia, serif;
--gs-font-sans:    "Inter", -apple-system, "Segoe UI", sans-serif;
--gs-font-mono:    "JetBrains Mono", ui-monospace, "Cascadia Mono", monospace;
```

Load from Google Fonts: `Instrument Serif` (400 + 400 italic) and `Inter` (400/500/600).

| Role | Font | Size / line-height | Weight | Notes |
|---|---|---|---|---|
| Section eyebrow | sans | 11px / 1.2 | 500 | uppercase, `letter-spacing: .12em`, `--gs-ink-muted`, prefixed `[01]` |
| Display heading | **serif** | 44px / 1.12 | 400 | the tail of the sentence fades — see 3.1 |
| Card title | **serif** | 22px / 1.3 | 400 | |
| Body | sans | 14px / 1.55 | 400 | `--gs-ink-muted` |
| Label above a value | sans | 11px / 1.2 | 500 | uppercase, `letter-spacing: .08em`, `--gs-ink-faint` |
| **Metric value** | **serif** | 40px / 1.0 | 400 | Big numbers are serif. This is the signature move (`$2,900` in the reference). Risk score, delta-T and battery percentage all use it. |
| Table / dense data | mono | 13px / 1.5 | 400 | tabular alignment for timestamps and delta-T |
| Button | sans | 13px / 1 | 500 | |

### 3.1 The "fading tail" heading

The reference renders a headline whose final clause fades to a muted color:

> Get faster payouts, more control, and less chasing with exclu**sive features.**
> (the bold part is rendered in `--gs-ink-faint`)

Reproduce it by wrapping the last few words in `<span class="tail">` colored
`--gs-ink-faint`. Use this **once**, on the dashboard hero line only.

## 4. Geometry and elevation

```css
--gs-radius-card:  24px;   /* outer cards */
--gs-radius-inner: 16px;   /* white inner panel */
--gs-radius-field: 12px;   /* rows, inputs, select-like rows */
--gs-radius-pill:  999px;  /* all buttons, badges, chips */

--gs-gap:          16px;   /* gap between cards in a grid */
--gs-pad-card:     32px;   /* card padding, 24px below 900px */
--gs-maxw:         1180px; /* content max width, centered */

--gs-shadow-panel: 0 18px 40px -24px rgba(20,25,26,.35);  /* white inner panel */
--gs-shadow-pop:   0 2px 8px -2px rgba(20,25,26,.18);     /* buttons on lime/dark */
```

Borders are nearly absent. Separation comes from surface color plus the 16px gap.
The only hairline borders are `1px solid var(--gs-line)` on table rows and inner fields.

### 4.1 Grid overlay

Dark cards carry a faint square grid at roughly 4% white:

```css
background-image:
  linear-gradient(to right,  rgba(255,255,255,.04) 1px, transparent 1px),
  linear-gradient(to bottom, rgba(255,255,255,.04) 1px, transparent 1px);
background-size: 40px 40px;
```

The same grid at `rgba(20,25,26,.06)`, about 48px tall and full-bleed, forms the thin
divider band the reference shows between sections. Use it once, above the Session
section.

## 5. Components

| Component | Spec |
|---|---|
| `Button` | Variants `dark` (bg `--gs-surface-dark`, text `--gs-ink-invert`), `white` (bg white, text `--gs-ink`), `lime` (bg `--gs-lime`, text `--gs-lime-ink`), `ghost` (transparent, 1px `--gs-line`). All pill, `padding: 10px 18px`. Primary actions carry a trailing arrow. |
| `Card` | `radius-card`, `pad-card`, one of the surfaces via a `tone` prop: `dark`, `grey`, `lime`, `white` (white with a 1px `--gs-line` border, for vitals tiles and engineering panels) or `plain` (no fill, no padding, never clips). |
| `Segmented` | Pill group in a white, 1px-line track; the active item is `--gs-surface-dark` with inverted ink. Used for the dashboard's Patient/Engineering switch. |
| `Meter` | 8px pill track in `--gs-surface-grey`, filled in `ink`, `ok`, `warn` or `danger`, with an optional 2px ink marker for a limit. The caller picks the tone from backend state. |
| `KeyValue` | Label/value rows divided by `--gs-line`; label in muted sans 13px, value in mono 13px, right-aligned. The engineering view's readouts. |
| `Panel` | The white inner "device screen": white background, `radius-inner`, `shadow-panel`, `padding: 20px`. Every chart lives in a Panel inside a Card. |
| `Badge` | Pill, 1px border in the mode color, 6px dot, sans 12px. |
| `FieldRow` | The reference's `$ / Client pays / USD` row: `radius-field`, white background, 1px `--gs-line`, 14px padding, a 32px square leading icon chip (grey, or lime when active), tiny label above the value. Reused for "Last check", "Next check" and the device status rows. |
| `Toggle` | The Early Pay switch: 52x30 pill, 24px white knob, on = `--gs-surface-dark`, off = `--gs-line`. Used for the auto-mode override and the demo simulator switch. |
| `SectionHeader` | Eyebrow plus serif display heading on the left, action buttons stacked on the right — mirrors the reference's Sign-in / Create-invoice pair. |

## 6. Layout

A 12-column grid at `--gs-maxw`, `--gs-gap` gutters, 64px of vertical rhythm between
sections.

```
[ SectionHeader ....................................... ][ actions ]

[ ECG LIVE   — dark card, span 8 ......... ][ RISK NOW — grey,  span 4 ]
[ RISK TREND — grey card, span 8 ......... ][ DEVICE   — plain, span 4 ]

[ FOOT CHECK — lime card, span 12 (copy left / white panel right) ]

--- grid divider band ---

[ SESSION SUMMARY — grey card, span 7 ][ MODE BREAKDOWN — dark, span 5 ]
```

The lime Foot-Check card deliberately mirrors the reference's "Crypto Payout" card:
copy and a bullet list on the left, a white device panel holding the actionable
control on the right.

**Breakpoints.** At 1200px and above, as drawn. Between 900 and 1199px the 8/4 pairs
collapse to stacked full-width cards while the lime split is preserved. Below 900px
everything is a single column, `--gs-pad-card` drops to 24px and charts shrink to
220px tall.

## 7. Motion

Restrained. `transition: 160ms ease` on hover, for buttons and rows only. The ECG
trace scrolls by redrawing on the animation frame — never CSS-animate the chart. No
entrance animations and no parallax.

## 8. Do and don't

- **Do** put every chart on a white Panel inside a colored Card.
- **Do** use the serif for large numbers. It is the strongest signature of the reference.
- **Don't** use more than one lime element per screen.
- **Don't** add shadows to outer cards. They are flat; only the inner panel floats.
- **Don't** use pure black or neutral grey — every neutral here is warm-tinted.
- **Don't** introduce a second accent hue. Status is carried by the muted mode colors only.
