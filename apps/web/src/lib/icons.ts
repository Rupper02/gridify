// Canvas-drawn map icons for the dark map: transformer (two circles), load (triangle) and open point
// (square). Projects are HTML markers (components/MapMarkers.tsx), not map icons.

import type { Map as MLMap } from "maplibre-gl";

import { C } from "../theme";

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

export function addIcons(map: MLMap): void {
  addIcon(map, "load", 16, 14, (x) => {
    x.fillStyle = "#8b98a9";
    x.strokeStyle = C.night;
    x.beginPath();
    x.moveTo(2, 2);
    x.lineTo(14, 2);
    x.lineTo(8, 12);
    x.closePath();
    x.fill();
    x.stroke();
  });
  addIcon(map, "trafo", 26, 32, (x) => {
    x.lineWidth = 2;
    x.strokeStyle = C.ink;
    [11, 21].forEach((y, i) => {
      x.fillStyle = i ? "rgba(21,32,49,0.7)" : C.substation;
      x.beginPath();
      x.arc(13, y, 8, 0, Math.PI * 2);
      x.fill();
      x.stroke();
    });
  });
  addIcon(map, "openpt", 12, 12, (x) => {
    x.fillStyle = C.substation;
    x.strokeStyle = C.mute;
    x.lineWidth = 1.5;
    x.fillRect(2, 2, 8, 8);
    x.strokeRect(2, 2, 8, 8);
  });
}
