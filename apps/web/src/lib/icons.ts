// Canvas-drawn map icons: one per technology × status variant, plus transformer, load and open-point.

import type { Map as MLMap } from "maplibre-gl";

type Draw = (ctx: CanvasRenderingContext2D) => void;

function addIcon(map: MLMap, name: string, w: number, h: number, draw: Draw): void {
  const pr = 2;
  const c = document.createElement("canvas");
  c.width = w * pr;
  c.height = h * pr;
  const ctx = c.getContext("2d")!;
  ctx.scale(pr, pr);
  draw(ctx);
  if (map.hasImage(name)) map.removeImage(name);
  map.addImage(name, ctx.getImageData(0, 0, w * pr, h * pr), { pixelRatio: pr });
}

const VARIANTS = {
  p1: { fill: "#16a34a", stroke: "#ffffff", glyph: "#ffffff", dash: [] as number[] },
  p2: { fill: "#2563eb", stroke: "#ffffff", glyph: "#ffffff", dash: [] as number[] },
  ghost: { fill: "rgba(219,234,254,0.9)", stroke: "#2563eb", glyph: "#2563eb", dash: [3, 2] },
  rej: { fill: "#f3f4f6", stroke: "#9ca3af", glyph: "#9ca3af", dash: [2, 2] },
};

export function addIcons(map: MLMap): void {
  const S = 36;
  const C = S / 2;
  const rr = (ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) => {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  };
  for (const [vk, v] of Object.entries(VARIANTS)) {
    const solid = vk === "p1" || vk === "p2";
    const body = (ctx: CanvasRenderingContext2D, path: () => void) => {
      ctx.fillStyle = v.fill;
      path();
      ctx.fill();
      ctx.setLineDash(v.dash);
      ctx.lineWidth = solid ? 2.5 : 2;
      ctx.strokeStyle = v.stroke;
      path();
      ctx.stroke();
      ctx.setLineDash([]);
    };
    addIcon(map, `solar-${vk}`, S, S, (ctx) => {
      body(ctx, () => rr(ctx, 5, 5, 26, 26, 3));
      ctx.strokeStyle = v.glyph;
      ctx.lineWidth = 1.6;
      ctx.beginPath();
      ctx.moveTo(6, C);
      ctx.lineTo(30, C);
      ctx.moveTo(C, 6);
      ctx.lineTo(C, 30);
      ctx.stroke();
    });
    addIcon(map, `wind-${vk}`, S, S, (ctx) => {
      body(ctx, () => {
        ctx.beginPath();
        ctx.arc(C, C, 14, 0, Math.PI * 2);
      });
      ctx.strokeStyle = v.glyph;
      ctx.lineWidth = 2.6;
      ctx.lineCap = "round";
      [-Math.PI / 2, Math.PI / 6, (5 * Math.PI) / 6].forEach((a) => {
        ctx.beginPath();
        ctx.moveTo(C, C);
        ctx.lineTo(C + Math.cos(a) * 9, C + Math.sin(a) * 9);
        ctx.stroke();
      });
    });
    addIcon(map, `battery-${vk}`, S, S, (ctx) => {
      ctx.fillStyle = solid ? v.fill : v.stroke;
      ctx.fillRect(30, 14, 4, 8);
      body(ctx, () => rr(ctx, 3, 8, 27, 20, 3));
      ctx.strokeStyle = v.glyph;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(12, 12);
      ctx.lineTo(12, 24);
      ctx.moveTo(21, 12);
      ctx.lineTo(21, 24);
      ctx.stroke();
    });
  }
  addIcon(map, "trafo", 30, 30, (ctx) => {
    ctx.fillStyle = "rgba(255,255,255,0.9)";
    ctx.beginPath();
    ctx.arc(15, 15, 14, 0, Math.PI * 2);
    ctx.fill();
    ctx.lineWidth = 2.4;
    ctx.strokeStyle = "#111827";
    [10.5, 19.5].forEach((y, i) => {
      ctx.fillStyle = i ? "rgba(255,255,255,0.6)" : "#ffffff";
      ctx.beginPath();
      ctx.arc(15, y, 7, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
    });
  });
  (
    [
      ["load", "#a8a29e"],
      ["load-h", "#57534e"],
    ] as const
  ).forEach(([n, c]) =>
    addIcon(map, n, 20, 26, (ctx) => {
      ctx.strokeStyle = c;
      ctx.lineWidth = 1.2;
      ctx.beginPath();
      ctx.moveTo(10, 0);
      ctx.lineTo(10, 10);
      ctx.stroke();
      ctx.fillStyle = c;
      ctx.strokeStyle = "#ffffff";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(3, 10);
      ctx.lineTo(17, 10);
      ctx.lineTo(10, 22);
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
    }),
  );
  addIcon(map, "openpt", 12, 12, (ctx) => {
    ctx.fillStyle = "#ffffff";
    ctx.strokeStyle = "#64748b";
    ctx.lineWidth = 1.5;
    ctx.fillRect(2, 2, 8, 8);
    ctx.strokeRect(2, 2, 8, 8);
  });
}
