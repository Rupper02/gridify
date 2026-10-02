import { TechIcon } from "./TechIcon";

export function Legend({ onClose }: { onClose: () => void }) {
  return (
    <div className="legend">
      <div className="row" style={{ justifyContent: "space-between", gap: 10 }}>
        <span className="caps">Legend</span>
        <button className="btn plain" style={{ fontSize: 14, lineHeight: 1, color: "var(--mute2)" }} onClick={onClose}>×</button>
      </div>
      <div className="grid">
        <div><TechIcon tech="solar" size={16} color="#374151" />Solar PV</div>
        <div><svg width="16" height="16" viewBox="0 0 16 16"><polygon points="3,5 13,5 8,13" fill="#a8a29e" /></svg>Load (sized by MW)</div>
        <div><TechIcon tech="wind" size={16} color="#374151" />Wind</div>
        <div>
          <svg width="16" height="16" viewBox="0 0 16 16">
            <circle cx="8" cy="5.5" r="4" fill="#fff" stroke="#111827" strokeWidth="1.6" />
            <circle cx="8" cy="10.5" r="4" fill="#fff" fillOpacity="0.6" stroke="#111827" strokeWidth="1.6" />
          </svg>
          Transformer
        </div>
        <div><TechIcon tech="battery" size={16} color="#374151" />Battery</div>
        <div>
          <svg width="16" height="16" viewBox="0 0 16 16">
            <line x1="1" y1="8" x2="15" y2="8" stroke="#94a3b8" strokeWidth="3" />
            <circle cx="3" cy="8" r="2.2" fill="#64748b" stroke="#fff" />
            <circle cx="13" cy="8" r="2.2" fill="#64748b" stroke="#fff" />
          </svg>
          Line · bus
        </div>
        <div><svg width="16" height="16" viewBox="0 0 16 16"><line x1="1" y1="8" x2="15" y2="8" stroke="#dc2626" strokeWidth="4" /></svg>Overloaded line</div>
        <div>
          <svg width="16" height="16" viewBox="0 0 16 16">
            <line x1="1" y1="8" x2="15" y2="8" stroke="#cbd5e1" strokeWidth="1.2" strokeDasharray="2 2" />
            <rect x="5" y="5" width="6" height="6" fill="#fff" stroke="#94a3b8" strokeWidth="1.2" />
          </svg>
          Open point
        </div>
        <div><svg width="16" height="16" viewBox="0 0 16 16"><line x1="1" y1="8" x2="15" y2="8" stroke="#d97706" strokeWidth="3.4" strokeDasharray="4 2.5" /></svg>Binding constraint</div>
        <div>
          <svg width="16" height="16" viewBox="0 0 16 16">
            <circle cx="8" cy="8" r="5.5" fill="rgba(220,38,38,0.1)" stroke="#dc2626" strokeWidth="1.8" />
            <circle cx="8" cy="8" r="2" fill="#64748b" />
          </svg>
          Voltage breach
        </div>
        <div><svg width="16" height="16" viewBox="0 0 16 16"><circle cx="8" cy="8" r="6" fill="#0d9488" stroke="#ffffff" strokeWidth="1.6" /></svg>Existing generation</div>
      </div>
      <div className="phases">
        <span><span className="swatch" style={{ background: "#16a34a" }} />Phase 1</span>
        <span><span className="swatch" style={{ background: "#2563eb" }} />Phase 2</span>
        <span><span className="swatch" style={{ background: "#fef3c7", border: "1.5px dashed #d97706" }} />Deferred</span>
        <span><span className="swatch" style={{ background: "#f3f4f6", border: "1px dashed #9ca3af" }} />Rejected</span>
      </div>
    </div>
  );
}
