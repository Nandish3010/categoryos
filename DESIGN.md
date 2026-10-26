# CategoryOS design system

Dark only, one set of tokens, defined in `frontend/app/globals.css` via Tailwind 4 `@theme`.
No gradients, no glow. Decision first: the verdict and the rupee number lead every screen.

## Colour
| Token | Value | Use |
|---|---|---|
| `bg` | `#0a0a0b` | page |
| `surface` | `#111114` | cards, panels |
| `surface-2` | `#17171b` | raised rows, inputs |
| `border` | `#26262c` | all dividers |
| `text` | `#ededf0` | primary text |
| `text-dim` | `#a1a1aa` | secondary text |
| `accent` | `#6ea8fe` | primary action, focus ring, links |
| `ok` | `#4ade80` | list, verified |
| `warn` | `#fbbf24` | negotiate, changed-row flash, needs data |
| `bad` | `#f87171` | reject, rejected claims |

## Type
Geist Sans for text, Geist Mono for source chips and ids. Scale: 12, 14, 16, 20, 28, 36 px.
All numbers use tabular figures. The largest figure on a screen is the rupee capital at risk (36 px).

## Shape and spacing
4 px grid. Card radius 8, chip radius 6. Table rows 40 px. Touch targets at least 44 px on small screens.
Icons: lucide at 16 px.

## Verdicts
Always icon + text + colour, never colour alone.

| Verdict | Icon | Colour |
|---|---|---|
| List | check-circle | ok |
| Negotiate | handshake | warn |
| Reject | x-circle | bad |
| Needs data | help-circle | warn |

## Layout (workspace)
Top bar 48 px; left rail 240 px; centre max 880 px; right panel 320 px.
At 1280 px and above: three columns. 900 to 1279 px: rail collapses to icons, right panel is a toggled drawer
with the verifier summary pinned. Below 900 px: one column in decision order with a sticky Approve bar.

## Components
Chip, Stat, Slider, DataTable, ClaimRow, TraceItem, PanelHeader, Banner, Skeleton (in `frontend/components`).

## Motion
Numbers tween 250 ms. Rows whose verdict changed flash amber for 600 ms and carry a "was X" tag for 3 s.
The banner delta chip clears after 4 s. `prefers-reduced-motion` makes everything instant.

## Focus and accessibility
2 px accent focus ring with 2 px offset. Range inputs carry `aria-valuetext`; arrows move one step,
Shift+arrow moves five. An `aria-live` region announces lever results.
