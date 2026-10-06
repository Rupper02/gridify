// A clock for live elapsed times (a running agent, the reviewer reading the gate): ticks only while something is live.

import { useEffect, useState } from "react";

export function useNow(live: boolean, everyMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!live) return;
    setNow(Date.now());
    const id = window.setInterval(() => setNow(Date.now()), everyMs);
    return () => window.clearInterval(id);
  }, [live, everyMs]);
  return now;
}
