# Gridify Glass: the planner's design system

The planner's visual language: dark, flat glass panels floating over a full-bleed map, one interactive accent, and
colour reserved for what the engine reports (loading, voltage, breaches). The implementation is `apps/web/src/styles.css`
(the tokens are CSS custom properties on `:root`) and `apps/web/src/theme.ts`; where this page and the code differ, the
code is current.

| File | What it is |
|---|---|
| `palette.dc.html` | The colour sheet: base, accent, states, branch hues, demand-profile glyphs, the line language |
| `components.dc.html` | The component sheet: every reusable piece with its states (panels, buttons, the branch capsule, the demand-profile control, segmented tabs, switches, technology icons, the GSP gauge, diff tiles, the year slider). Some pieces on it are for planned features and are not in the planner yet |

Open either file in a browser, next to `support.js`.

## Tokens

**Base**

| Token | Value | Use |
|---|---|---|
| `--night` | `#0b111a` | Background |
| `--substation` | `#152031` | Raised surfaces |
| `--ambient` | `#2b3d57` | Ambient lines |
| `--ink` / `--ink-2` / `--ink-3` | `#eaf0f7` / `#c9d6e8` / `#dbe4ef` | Text, strongest to softest |
| `--mute` / `--mute-2` | `#9aa9bc` / `#7d8da3` | Secondary text, captions |

**Accent and states**

| Token | Value | Use |
|---|---|---|
| `--accent` | `#7ce3ff` | The single interactive accent; also live flow on the map |
| `--existing` | `#2fbfa5` | Generation connected today |
| `--amber` | `#ffc36b` | Near a limit, stale, needs attention |
| `--red` | `#ff6b6b` | A limit breached |

**Branch hues.** `main` is `#c9d6e8` (silver, read-only); each branch gets its own hue (`theme.ts`), which frames the
workspace and rings what exists only on that branch. Tints append alpha to the hue: `1f` for backgrounds, `80` for
borders, `1c` for glow.

**Type.** Geist for the interface, Geist Mono for identifiers and figures (bus and branch names, MW, %, pu). Sizes 10.5
to 19 px.

**Shape.** Panels 14–20 px radius; cards and inner boxes 10–12; buttons 9–12; chips, toggles and segmented controls are
full pills. Panels use the `--glass` gradient, a 1 px light border and a soft shadow (`--glass-bd`, `--glass-sh`).

**Motion.** Easing `cubic-bezier(0.16, 1, 0.3, 1)` (`--ease`); the side panel slides in 320 ms. Every animation is off
under `prefers-reduced-motion`.

## Assets

- **Icons:** Phosphor (`@phosphor-icons/react`); each technology's icon is `TECH_ICON` in `apps/web/src/components/ui.tsx`.
- **Map:** CARTO Dark Matter without labels; the attribution stays visible. Transformer, load and open-point symbols are
  drawn on canvas (`apps/web/src/lib/icons.ts`).
