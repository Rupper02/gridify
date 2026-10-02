/** Small inline technology glyphs used in lists and the legend. */
export function TechIcon({ tech, size = 11, color = "#6b7280" }: { tech: string | null | undefined; size?: number; color?: string }) {
  const stroke = size >= 16 ? 1.5 : 1.4;
  if (tech === "solar")
    return (
      <svg width={size} height={size} viewBox="0 0 16 16" style={{ flex: "none" }}>
        <rect x="2" y="2" width="12" height="12" rx="1.5" fill={color} />
        <line x1="2" y1="8" x2="14" y2="8" stroke="#fff" strokeWidth={stroke} />
        <line x1="8" y1="2" x2="8" y2="14" stroke="#fff" strokeWidth={stroke} />
      </svg>
    );
  if (tech === "wind")
    return (
      <svg width={size} height={size} viewBox="0 0 16 16" style={{ flex: "none" }}>
        <circle cx="8" cy="8" r="7" fill={color} />
        <line x1="8" y1="8" x2="8" y2="3" stroke="#fff" strokeWidth="1.8" strokeLinecap="round" />
        <line x1="8" y1="8" x2="12.3" y2="10.5" stroke="#fff" strokeWidth="1.8" strokeLinecap="round" />
        <line x1="8" y1="8" x2="3.7" y2="10.5" stroke="#fff" strokeWidth="1.8" strokeLinecap="round" />
      </svg>
    );
  if (tech === "battery")
    return (
      <svg width={size + 2} height={size} viewBox="0 0 18 16" style={{ flex: "none" }}>
        <rect x="15" y="5.5" width="2.5" height="5" fill={color} />
        <rect x="1" y="3" width="14" height="10" rx="1.5" fill={color} />
        <line x1="5.7" y1="5" x2="5.7" y2="11" stroke="#fff" strokeWidth="1.4" />
        <line x1="10.3" y1="5" x2="10.3" y2="11" stroke="#fff" strokeWidth="1.4" />
      </svg>
    );
  return null;
}
