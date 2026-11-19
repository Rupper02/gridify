"""A branch's year: its connections in service by a plan year, run through a whole grown year (half-hour by
half-hour, about 16 minutes on one core) as a job on the single worker, and compared with the catalogued grown year of
the same year and pathway.

The run file is the cached result. It is named by `ResultCache.key` (the base run, so the plan year and pathway; the in-service
connections; the grid's baseline; the engine fingerprint), so an unchanged branch is not solved twice and a code change retires old files."""

from __future__ import annotations

import os

from gridify_optimizer import runs
from gridify_optimizer.config import FORECASTS
from gridify_optimizer.timeseries import growth_scale, run_year
from gridify_optimizer.years import in_service

from .cache import ResultCache, connections_key
from .errors import Invalid
from .grid import Grid
from .service import PlanService, plan_params


class YearRuns:
    """Start a branch's year as a job; the result is a run id the `/runs` endpoints serve."""

    def __init__(self, plans: PlanService, grid: Grid, cache: ResultCache, files: runs.RunFiles):
        self.plans, self.grid, self.cache, self.files = plans, grid, cache, files
        self.folder = files.folder

    def prepare(self, branch_id: str, year: int, pathway: str):
        """What the job computes: (its key, its function). Refuses a year and pathway the catalogue has no grown year for
        (nothing to compare with), and a branch with no connection in service by then."""
        before = f"{year}-{pathway}"
        bases = self.files.cat.bases
        if before not in bases or pathway not in FORECASTS:
            raise Invalid(f"a branch's year runs on a catalogued grown year: one of {', '.join(bases)}")
        if not self.files.path(before).exists():
            raise Invalid(f"the grown year '{before}' has no file yet: {self.files.info(before).make}")
        b = self.plans.inputs(branch_id)
        conns = in_service(b.connections, year)
        if not conns:
            raise Invalid(f"no connection on this branch is in service by {year}: the grown year itself is the answer")
        # the base run carries the plan year: two years with the same connections in service are different runs
        key = self.cache.key(f"year:{before}", plan_params({"scenario": pathway}), connections_key(conns), self.grid.baseline())
        run_id = runs.branch_run_id(key)
        out = self.files.path(run_id)
        about = {"label": f"{year} {FORECASTS[pathway]['label']} + branch '{b.branch['name']}'", "year": year,
                 "pathway": pathway, "before": before, "branch_id": branch_id}

        def job(progress, _publish) -> dict:
            done = {"run_id": run_id, "before": before}
            if out.exists():  # solved before for exactly these inputs
                return done
            flows = self.folder / self.files.cat.measured_flows
            progress("growing demand to the year", 0.0)
            scale = growth_scale(flows, year, pathway, net_factory=self.grid.build_net)
            tmp = out.with_name(out.stem + ".part.npz")
            try:
                run_year(flows, tmp, net_factory=self.grid.build_net, reactive="screened", scale=scale, connections=conns,
                         plan_year=year, about=about,
                         progress=lambda j, n, s: progress(f"{j:,} of {n:,} half-hours solved, {s / 60:.0f} min", j / n))
                os.replace(tmp, out)  # whole or not at all: a cancelled or failed run leaves no file under the run's name
            finally:
                tmp.unlink(missing_ok=True)
            return done

        return key, job
