// The browser around the planner: the viewport's size (debounced on resize) and the reduced-motion preference.

import { useEffect, useState } from "react";

export function useViewport() {
  const [vp, setVp] = useState({ w: window.innerWidth, h: window.innerHeight });
  useEffect(() => {
    let t = 0;
    const on = () => {
      window.clearTimeout(t);
      t = window.setTimeout(() => setVp({ w: window.innerWidth, h: window.innerHeight }), 80);
    };
    window.addEventListener("resize", on);
    return () => window.removeEventListener("resize", on);
  }, []);
  return vp;
}

export function useReducedMotion() {
  const q = "(prefers-reduced-motion: reduce)";
  const [reduce, setReduce] = useState(() => window.matchMedia?.(q).matches ?? false);
  useEffect(() => {
    const m = window.matchMedia?.(q);
    if (!m) return;
    const on = () => setReduce(m.matches);
    m.addEventListener("change", on);
    return () => m.removeEventListener("change", on);
  }, []);
  return reduce;
}
