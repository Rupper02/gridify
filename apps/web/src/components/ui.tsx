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
