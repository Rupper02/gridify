// Shared building blocks (the component sheet in docs/design/gridforge-glass): the tech icon, the
// profile glyph, the switch, the year stepper, the diff tile, the GSP gauge and the branch-hue vars.

import {
  ArrowRight,
  BatteryCharging,
  Buildings,
  Drop,
  Engine,
  Fire,
  Lightning,
  Minus,
  Plant,
  Plus,
  SolarPanel,
  SolarRoof,
  Wind,
  type Icon,
} from "@phosphor-icons/react";
import type { CSSProperties, ReactNode } from "react";
import Markdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import { type ModelIndex, nameElements } from "../lib/derive";
import { citeSteps, citedStep } from "../lib/markdown";
import { C, isTech, tint } from "../theme";
import type { Tech } from "../types";

const TECH_ICON: Record<Tech, Icon> = {
  solar: SolarPanel,
  wind: Wind,
  battery: BatteryCharging,
  hybrid: SolarRoof,
  gas: Fire,
  gas_engine: Engine,
  biomass: Plant,
  electrolyser: Drop,
  demand: Buildings,
  other: Lightning,
};

export function TechIcon({ tech, size = 15, color, weight = "regular" }: { tech: string | null | undefined; size?: number; color?: string; weight?: "regular" | "bold" | "fill" }) {
  const I = isTech(tech) ? TECH_ICON[tech] : Lightning;
  return <I size={size} color={color} weight={weight} aria-hidden />;
}

/** A tech icon on a tinted tile in a status colour. */
export function TechTile({ tech, c, size = 28 }: { tech: string | null | undefined; c: string; size?: number }) {
  return (
    <span className="tech-tile" style={{ width: size, height: size, background: tint(c, "1f") }}>
      <TechIcon tech={tech} size={Math.round(size * 0.54)} color={c} />
    </span>
  );
}

/** The 1/2/3-bar meter that stands for a demand profile. */
export function ProfileGlyph({ bars, on = true, big = false }: { bars: number; on?: boolean; big?: boolean }) {
  const lit = on ? C.accent : C.mute;
  const off = "rgba(255,255,255,0.15)";
  const h = big ? [9, 15, 22] : [5, 8, 11];
  const w = big ? 5 : 3;
  return (
    <span className="glyph" style={{ height: h[2], gap: big ? 3 : 2 }} aria-hidden>
      {h.map((x, i) => (
        <span key={i} style={{ width: w, height: x, background: i < bars ? lit : off, borderRadius: big ? 1.5 : 1 }} />
      ))}
    </span>
  );
}

export function Switch({ on }: { on: boolean }) {
  return (
    <span className={`switch${on ? " on" : ""}`} aria-hidden>
      <span />
    </span>
  );
}

export function Stepper({ value, onDec, onInc, small = false, label, words = ["Earlier", "Later"] }: { value: ReactNode; onDec: () => void; onInc: () => void; small?: boolean; label: string; words?: [string, string] }) {
  return (
    <span className={`stepper${small ? " sm" : ""}`}>
      <button onClick={onDec} aria-label={`${words[0]} ${label}`}>
        <Minus size={small ? 12 : 13} />
      </button>
      <b>{value}</b>
      <button onClick={onInc} aria-label={`${words[1]} ${label}`}>
        <Plus size={small ? 12 : 13} />
      </button>
    </span>
  );
}

export function DiffTile({ label, base, head, delta, c }: { label: string; base: string; head: string; delta: string; c: string }) {
  return (
    <div className="tile">
      <span style={{ fontSize: 11, color: C.mute }}>{label}</span>
      <span style={{ display: "flex", alignItems: "baseline", flexWrap: "wrap", gap: "2px 6px", minWidth: 0 }}>
        <span className="mono" style={{ fontSize: 13, color: C.mute2 }}>{base}</span>
        <ArrowRight size={11} color={C.mute2} />
        <span className="mono" style={{ fontSize: 18, fontWeight: 600 }}>{head}</span>
        <span className="mono" style={{ marginLeft: "auto", fontSize: 11.5, fontWeight: 600, color: c }}>{delta}</span>
      </span>
    </div>
  );
}

/** An element's figure over the plan years as thin bars on a baseline, its limit as a dashed line (the rating, at 100%,
 * unless the caller names another: a bus's voltage limit in pu), the viewed year brighter; a year not solved shows as a
 * stub. Each bar names its year and figure on hover (`fmt`). Colours are the caller's: the planner's loading tokens
 * (`loadColor`), the same the map and the readings use, or the voltage ones. */
export function Sparkline({
  points, year, color, limit = 100, fmt = (v) => `${Math.round(v)}%`,
}: {
  points: { year: number; pct: number | null }[];
  year: number;
  color: (v: number | null) => string;
  limit?: number;
  fmt?: (v: number) => string;
}) {
  const w = 10;
  const gap = 4;
  const h = 30;
  const width = points.length * (w + gap) - gap;
  const max = Math.max(limit * 1.1, ...points.map((p) => p.pct ?? 0));
  const yOf = (v: number) => h - (v / max) * h;
  return (
    <svg className="spark" width={width} height={h + 2} role="img" aria-label="By plan year">
      <line className="spark-rating" x1={0} x2={width} y1={yOf(limit)} y2={yOf(limit)} strokeDasharray="2 3" />
      {points.map((p, i) => {
        const x = i * (w + gap);
        const on = p.year === year;
        if (p.pct == null)
          return (
            <g key={p.year}>
              <title>{`${p.year}: not solved`}</title>
              <rect x={x} y={h - 2} width={w} height={2} fill="rgba(255,255,255,0.14)" />
            </g>
          );
        const bh = Math.max(2, h - yOf(p.pct));
        return (
          <g key={p.year}>
            <title>{`${p.year}: ${fmt(p.pct)}`}</title>
            <rect x={x} y={h - bh} width={w} height={bh} rx={2} fill={color(p.pct)} opacity={on ? 1 : 0.5} />
          </g>
        );
      })}
      <line className="spark-base" x1={0} x2={width} y1={h + 0.5} y2={h + 0.5} />
    </svg>
  );
}

export function Gauge({ ticks }: { ticks: string[] }) {
  return (
    <div className="gauge" aria-hidden>
      {ticks.map((c, i) => (
        <span key={i} style={{ background: c }} />
      ))}
    </div>
  );
}

/** The CSS vars a branch hue drives (frame, capsule, hue buttons, "this branch" tags). */
export function hueVars(hue: string, onMain: boolean): CSSProperties {
  return {
    "--hue": hue,
    "--hue-bd": onMain ? "rgba(255,255,255,0.16)" : tint(hue, "80"),
    "--hue-bg": onMain ? "rgba(255,255,255,0.06)" : tint(hue, "1f"),
    "--hue-chip": onMain ? "rgba(255,255,255,0.1)" : tint(hue, "2e"),
    "--hue-glow": tint(hue, "1c"),
  } as CSSProperties;
}

/** Citations become small numbered chips; any other link opens in a new tab. */
const MD_COMPONENTS: Components = {
  a: ({ href, children }) => {
    const step = citedStep(href);
    if (step) return <sup className="cite" title={`Traced to tool step ${step}`}>{children}</sup>;
    return <a href={href} target="_blank" rel="noreferrer">{children}</a>;
  },
};

/** An agent's text (an answer, the engineer's note) as markdown: elements named where they are, every `[step …]`
 * citation a numbered chip (a note carries none). The caller's container carries the `md` class. */
export function AgentText({ text, ix }: { text: string; ix: ModelIndex | null }) {
  return (
    <Markdown remarkPlugins={[remarkGfm]} components={MD_COMPONENTS}>
      {citeSteps(nameElements(text, ix))}
    </Markdown>
  );
}
