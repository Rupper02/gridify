"""Run the engine for a branch: read its inputs, start or join its run on the job worker, simulate the plan years
through the cache, shape the result for the map, and compare a branch with its parent."""

from __future__ import annotations

from collections.abc import Callable
from typing import NamedTuple

from gridify_optimizer import Connection, PlanDiff, PlanParams, PlanResult, diff_plans, simulate
from gridify_optimizer.config import FORECASTS

from ..errors import Conflict, Invalid, NotSolved
from ..grid import Grid
from ..storage import repository
from ..storage.scenarios import ScenarioStore
from .cache import ResultCache, connections_key
from .jobs import JobRunner

YEAR_STOPPED = ("stopped so a branch's plan years could solve first. Nothing of it was kept: run the year again once the "
                "branch holds what you want to study")


class BranchInputs(NamedTuple):
    """What a branch's run depends on."""

    branch: dict
    connections: list[Connection]
    params: PlanParams


def plan_params(branch: dict) -> PlanParams:
    """A branch's demand profile as engine parameters: a pathway's anchors (the grid grows per primary on its own
    curves for it), or the branch's own for `custom`."""
    scenario = branch["scenario"]
    if scenario in FORECASTS:
        f = FORECASTS[scenario]
        return PlanParams(scenario=scenario, growth_2030=f["growth_2030"], growth_2035=f["growth_2035"])
    if scenario != "custom":
        raise Invalid(f"unknown demand pathway '{scenario}'")
    return PlanParams(scenario="custom", growth_2030=float(branch["growth_2030"]), growth_2035=float(branch["growth_2035"]))


class PlanService:
    """The engine behind the API's run and diff endpoints, with its collaborators handed in."""

    def __init__(self, grid: Grid, store: ScenarioStore, cache: ResultCache, jobs: JobRunner):
        self.grid = grid
        self.store = store
        self.cache = cache
        self.jobs = jobs

    def start_run(self, branch_id: str, view_year: int | None = None) -> dict:
        """Start a branch's run on the job worker: every plan year, `view_year` first. A run of the same inputs already
        queued or running is joined; a cached one finishes at once. A plan run never waits behind a branch's year."""
        b = self.inputs(branch_id)
        key = self.run_key(b)
        if not self.cache.has(key):  # a cached plan finishes at once: it need not stop anything
            self.stop_year_runs()
        return self.jobs.start("run", lambda progress, publish: self.run(b, progress=progress, publish=publish, view_year=view_year),
                               key=key)

    def simulate(self, branch_id: str) -> dict:
        """Run a branch and wait for it (scripts and tests; the planner uses `start_run`)."""
        self.stop_year_runs()
        return self.run(self.inputs(branch_id))

    def stop_year_runs(self) -> None:
        """A branch's year (up to twenty minutes on the one worker) stops at its next progress report, a few seconds,
        and leaves no file (`year_runs`: whole or not at all)."""
        self.jobs.stop_kind("year", YEAR_STOPPED)

    def inputs(self, branch_id: str) -> BranchInputs:
        with self.store.cursor() as con:
            branch = repository.require_branch(con, branch_id)
            conns = repository.connections(con, branch_id)
        return BranchInputs(branch, conns, plan_params(branch))

    def run_key(self, b: BranchInputs) -> str:
        """The identity of a branch's result: the same for a re-run with the same inputs, different as soon as anything
        changes (a job for one can serve both)."""
        return self.cache.key("plan", b.params, connections_key(b.connections), self.grid.baseline())

    def result(self, b: BranchInputs, *, progress=None, on_year=None, view_year: int | None = None,
               solve: bool = True, wait: bool = True) -> PlanResult:
        """Every plan year of a branch, through the cache (the in-process dict, the durable table, then the engine). A
        cached plan still reaches `on_year` year by year, the way a fresh one does."""
        baseline = self.grid.baseline()
        return self.cache.through(
            self.run_key(b), "plan", baseline=baseline, parse=PlanResult.model_validate_json,
            compute=lambda: simulate(b.connections, b.params, view_year=view_year, net_factory=self.grid.build_net,
                                     progress=progress, on_year=on_year, cache=self.cache.year_cache(baseline)),
            dump=lambda r: r.model_dump_json(),
            on_hit=(lambda r: [on_year(y) for y in r.years.values()]) if on_year else None, solve=solve, wait=wait,
        )

    def payload(self, b: BranchInputs, result: PlanResult | None = None) -> dict:
        """A branch's run as the planner renders it: every year, the demand profile and the run's key."""
        out = {"branch_id": b.branch["branch_id"], "run_key": self.run_key(b), "params": b.params.model_dump(), "years": {}}
        if result is not None:
            out["years"] = {k: v.model_dump() for k, v in result.years.items()}
        return out

    def run(self, b: BranchInputs, *, progress: Callable[[str, float], None] | None = None,
            publish: Callable[[dict], None] | None = None, view_year: int | None = None) -> dict:
        """Run a branch on the inputs read when the run was asked for (`inputs`), so a job computes exactly what its key
        names: every plan year, the viewed year first. `publish(payload)` receives the partial payload as each year
        lands, so the planner shows results while the rest are still solving."""
        out = self.payload(b)

        def on_year(yr) -> None:
            out["years"] = {**out["years"], str(yr.year): yr.model_dump()}
            if publish:
                publish(dict(out))

        result = self.result(b, progress=progress, on_year=on_year, view_year=view_year)
        return self.payload(b, result)

    def latest(self, branch_id: str) -> dict:
        """A branch's result for what it holds now, without solving: `NotSolved` until it has run."""
        b = self.inputs(branch_id)
        return self.payload(b, self.result(b, solve=False))

    def compare_with_parent(self, branch_id: str) -> dict:
        """The branch against its parent, year by year, on the branch's demand profile."""
        with self.store.cursor() as con:
            head = repository.require_branch(con, branch_id)
        if repository.is_main(head):
            raise Conflict("main has no parent to compare with")
        return {"base": head["parent_id"], **self.diff(branch_id, head["parent_id"]).model_dump()}

    def diff(self, head_id: str, base_id: str) -> PlanDiff:
        """The branch against its base, year by year. The branch must have run for what it holds now; the base's side
        is solved if need be, but never queued behind a run (`NotSolved` with `retry`)."""
        head_in = self.inputs(head_id)
        try:
            head = self.result(head_in, solve=False)
        except NotSolved:
            raise NotSolved("this branch has not been run for what it holds now: run it, then compare", retry=False) from None
        base_in = self.inputs(base_id)
        base_in = base_in._replace(params=head_in.params)  # like for like: the difference is the branch's connections
        base = self.result(base_in, wait=False)
        return diff_plans(base, head)
