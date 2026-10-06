// Rebase onto the parent (main, or the branch it was opened from): shown on a branch its parent moved past (`branch.behind`). Only the operator starts it: a preview first
// (the parent's changes taken in, the branch's own kept, every conflict to pick, none picked for them), then Rebase. The
// branch's result is out of date until it runs again.

import { ArrowsClockwise, GitBranch, Warning } from "@phosphor-icons/react";
import { useState } from "react";

import type { Branch, RebaseChange, RebasePick, RebasePreview } from "../types";


export function RebaseCard({ branch, parent, name, onPreview, onRebase }: {
  branch: Branch;
  /** what its parent is called: "main", or the parent branch's name */
  parent: string;
  name: (text: string) => string;
  onPreview: () => Promise<RebasePreview | null>;
  onRebase: (picks: Record<string, RebasePick>) => Promise<boolean>;
}) {
  const [preview, setPreview] = useState<RebasePreview | null>(null);
  const [picks, setPicks] = useState<Record<string, RebasePick>>({});
  const [busy, setBusy] = useState(false);
  const noAncestor = branch.fork === "none";
  const pickLabel: Record<RebasePick, string> = { parent: `${parent}'s`, branch: "this branch's", both: "both" };
  if (!branch.behind && !noAncestor && !preview) return null;

  const open = async () => {
    setBusy(true);
    setPreview(await onPreview());
    setPicks({});
    setBusy(false);
  };
  const apply = async () => {
    if (!preview) return;
    setBusy(true);
    const done = await onRebase(picks);
    setBusy(false);
    if (done) setPreview(null);
    else void open(); // refused: the parent may have moved again; show the rebase as it is now
  };
  const unpicked = preview ? preview.conflicts.filter((c) => !picks[c.id]).length : 0;
  const list = (title: string, xs: RebaseChange[]) =>
    xs.length > 0 && (
      <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
        <span style={{ fontSize: 11.5, fontWeight: 600 }}>{title}</span>
        {xs.map((c) => (
          <span key={c.point} className="gate-row info">{name(c.text)}</span>
        ))}
      </div>
    );

  return (
    <div className="gate-card" style={{ borderColor: "rgba(255,195,107,0.4)" }}>
      <span className="gate-state" data-tone="warn">
        <GitBranch size={14} weight="bold" />
        {branch.behind
          ? `${parent} received ${branch.behind} change${branch.behind === 1 ? "" : "s"} after this branch was opened`
          : noAncestor
            ? `Where this branch started from ${parent} is not known`
            : `Rebase onto ${parent}`}
      </span>
      {!preview ? (
        <>
          <span style={{ fontSize: 12, lineHeight: 1.45 }}>
            {noAncestor
              ? `It was opened from another branch before fork points were recorded, so ${parent}'s changes cannot be told from this branch's own. Rebase it onto ${parent}: every difference between the two is then yours to pick.`
              : `Merging now would undo ${branch.behind === 1 ? "it" : "them"}. Rebase this branch onto ${parent} to take ${branch.behind === 1 ? "it" : "them"} in: you see what changes and pick every conflict before anything is written.`}
          </span>
          <button className="btn" onClick={() => void open()} disabled={busy || branch.status !== "open"}>
            <ArrowsClockwise size={13} />
            Rebase onto {parent}…
          </button>
        </>
      ) : (
        <>
          {preview.fork === "rebuilt" && (
            <span className="mute" style={{ fontSize: 11, lineHeight: 1.4 }}>
              This branch is older than fork points: where it started was rebuilt from main's merge history (exact for projects, works and reinforcements;
              main's demand profile then is not recorded, so a difference in it is yours to pick).
            </span>
          )}
          {list(`From ${parent}, taken in`, preview.behind)}
          {list("This branch's own changes, kept", preview.own_changes)}
          {preview.conflicts.length > 0 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <span style={{ fontSize: 11.5, fontWeight: 600 }}>
                <Warning size={12} style={{ verticalAlign: -2 }} /> {preview.fork === "none" ? "Differences: pick a side for each" : "Changed on both sides: pick one for each"}
              </span>
              {preview.conflicts.map((c) => (
                <div key={c.id} style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                  <span style={{ fontSize: 12 }}>{name(c.text)}</span>
                  <div className="seg" role="radiogroup" aria-label={c.text} style={{ alignSelf: "flex-start" }}>
                    {c.options.map((o) => (
                      <button key={o} role="radio" aria-checked={picks[c.id] === o} className={picks[c.id] === o ? "on" : ""}
                        onClick={() => setPicks((p) => ({ ...p, [c.id]: o }))} style={{ padding: "0 10px" }}
                        title={o === "parent" ? name(c.parent) : o === "branch" ? name(c.branch) : "keep both"}>
                        {pickLabel[o]}
                      </button>
                    ))}
                  </div>
                  <span className="mute" style={{ fontSize: 11 }}>{parent}: {name(c.parent)} · this branch: {name(c.branch)}</span>
                </div>
              ))}
            </div>
          )}
          {preview.up_to_date && preview.conflicts.length === 0 && <span className="mute" style={{ fontSize: 12 }}>This branch already has everything {parent} has.</span>}
          <div style={{ display: "flex", gap: 8 }}>
            <button className="btn primary grow" onClick={() => void apply()} disabled={busy || unpicked > 0}
              title={unpicked ? `Pick ${unpicked} more conflict${unpicked === 1 ? "" : "s"} first` : `Write ${parent}'s state plus this branch's changes onto the branch`}>
              <ArrowsClockwise size={13} />
              {unpicked ? `Pick ${unpicked} more` : "Rebase"}
            </button>
            <button className="btn" onClick={() => setPreview(null)} disabled={busy}>
              Cancel
            </button>
          </div>
          <span className="mute" style={{ fontSize: 10.5 }}>The branch's result is out of date after a rebase: re-run it, then the gate judges it as usual.</span>
        </>
      )}
    </div>
  );
}
