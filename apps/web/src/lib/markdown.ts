/** An agent's reply is markdown; its figures are cited as "[step <id>]" or "[same step]". Turn each citation into a link
 * the renderer shows as a small numbered chip (the id stays in its title), so the prose reads cleanly. */
const CITE = /\s*\[(step\s+([^\]\s]+)|same step)\]/gi;
export const CITE_HREF = "#cite:";

export function citeSteps(text: string): string {
  let n = 0;
  let last = "";
  return text.replace(CITE, (_m, _all, id?: string) => {
    if (id) last = id;
    n += 1;
    return ` [${n}](${CITE_HREF}${encodeURIComponent(last)})`;
  });
}

/** The step id inside a citation link, or null for any other link. */
export function citedStep(href: string | undefined): string | null {
  return href?.startsWith(CITE_HREF) ? decodeURIComponent(href.slice(CITE_HREF.length)) : null;
}
