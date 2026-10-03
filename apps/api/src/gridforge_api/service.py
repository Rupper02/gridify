"""Run the engine for a branch: resolve parameters, build candidates, cache, enrich for the map,
and solve the plan year by year."""

import hashlib
import json
import time
from typing import NamedTuple

from gridforge_optimizer import (
    PLAN_YEARS,
    Candidate,
    ConsequenceDiff,
    OptimizeParams,
    OptimizeResult,
    Outage,
    OutageStudy,
    Reinforcement,
    Suggestion,
    YearResult,
    apply_reinforcement,
    diff_results,
    energisation_years,
    evaluate_year,
    evaluate_years,
    optimize,
    suggest_unblock,
)
from gridforge_optimizer.config import FORECASTS
from gridforge_optimizer.network import build_base_net

from . import narration, repository
from .cache import ResultCache, cand_key
from .schemas import OptimizeRequest
from .store import ScenarioStore
from .warehouse import Warehouse


def resolve_params(body: OptimizeRequest) -> OptimizeParams:
    """Resolve a request to concrete OptimizeParams (named DFES pathway -> feeder multipliers)."""
    if body.scenario in FORECASTS:
        scenario = body.scenario
        growth_2030 = FORECASTS[scenario]["growth_2030"]
        growth_2035 = FORECASTS[scenario]["growth_2035"]
    else:
        scenario = "custom"
        growth_2030, growth_2035 = body.growth_2030, body.growth_2035
    weights = {
        k: v for k, v in {
            "w_readiness": body.w_readiness, "w_need": body.w_need, "w_strategic": body.w_strategic,
        }.items() if v is not None
    }
    return OptimizeParams(growth_2030=growth_2030, growth_2035=growth_2035, scenario=scenario, **weights)


class BranchInputs(NamedTuple):
    """What a branch's run depends on (PlanService.inputs)."""

    req: OptimizeRequest
    cands: list[Candidate]
    ckey: str
    reinforcements: list[Reinforcement]
    outages: list[Outage]
    schedule: dict[str, int]


def reinf_key(reinforcements) -> str:
    """Cache-key part for simulated reinforcements ("" when none, so plain runs keep their keys)."""
    if not reinforcements:
        return ""
    return hashlib.md5(json.dumps([r.model_dump() for r in reinforcements], sort_keys=True).encode()).hexdigest()


def years_key(b: BranchInputs) -> str:
    """Cache-key part for what the years depend on beyond the queue: outages, schedule, reinforcements."""
    sig = [reinf_key(b.reinforcements), [o.model_dump() for o in b.outages], sorted(b.schedule.items())]
    return hashlib.md5(json.dumps(sig, sort_keys=True, default=str).encode()).hexdigest()


def reinforced_factory(reinforcements):
    """A net factory with the branch's simulated reinforcements applied (the base one when none)."""
    if not reinforcements:
        return build_base_net

    def factory():
        net = build_base_net()
        for r in reinforcements:
            apply_reinforcement(net, r)
        return net
    return factory


class PlanService:
    """The engine behind the API's optimize / diff / suggestion endpoints, with its collaborators
    (read-only warehouse, scenarios store, result cache, narrator) handed in."""

    def __init__(self, warehouse: Warehouse, store: ScenarioStore, cache: ResultCache,
                 narrator: narration.Narrator):
        self.warehouse = warehouse
        self.store = store
        self.cache = cache
        self.narrator = narrator

    def candidates(self, branch_id: str = "main") -> list[Candidate]:
        """The optimizer's candidate list for a branch (the projects added to it)."""
        with self.store.cursor() as con:
            rows = repository.candidate_rows(con, branch_id)
        return [
            Candidate(
                request_id=r["request_id"],
                bus_id=None if r["bus_id"] is None else int(r["bus_id"]),
                technology=r["technology"],
                rating_mw=None if r["rating_mw"] is None else float(r["rating_mw"]),
                readiness_score=float(r["readiness_score"]),
                strategic_fit=float(r["strategic_fit"]),
                readiness_rationale=r.get("readiness_rationale") or "",
                status=r["status"],
                review_reasons=r.get("review_reasons") or "",
                commissioning_year=(None if r.get("commissioning_year") is None else int(r["commissioning_year"])),
                import_mw=(None if r.get("import_mw") is None else float(r["import_mw"])),
            )
            for r in rows
        ]

    def inputs(self, branch_id: str) -> BranchInputs:
        """Everything a branch's run depends on, read once: its parameters, projects, simulated
        reinforcements, planned outages and the operator's scheduled years."""
        with self.store.cursor() as con:
            row = repository.require_branch(con, branch_id)
            reinf = repository.reinforcements(con, branch_id)
            outages = repository.outages(con, branch_id)
            rows = repository.candidate_rows(con, branch_id)
        cands = self.candidates(branch_id)
        schedule = {r["request_id"]: int(r["scheduled_year"]) for r in rows if r.get("scheduled_year") is not None}
        return BranchInputs(repository.branch_request(row), cands, cand_key(cands), reinf, outages, schedule)

    def compute(self, body: OptimizeRequest, cands: list[Candidate], ckey: str,
                reinforcements: list[Reinforcement] = (), progress=None) -> OptimizeResult:
        """Run the deterministic optimizer for a request + candidate set (+ the branch's simulated
        reinforcements).

        Three layers: the in-process dict, the durable `result_cache` table (survives restarts and is
        shared by every endpoint that needs the same run), then the engine. Keys include the model
        snapshot, the parameters, the candidate set, the reinforcements and the engine fingerprint."""
        params = resolve_params(body)
        key = self.cache.key("optimize", params, ckey, extra=reinf_key(reinforcements))
        if key in self.cache.compute:
            return self.cache.compute[key]
        cached = self.cache.get(key)
        if cached is not None:
            self.cache.compute[key] = OptimizeResult.model_validate_json(cached)
            return self.cache.compute[key]
        t0 = time.perf_counter()
        result = optimize(cands, params, list(reinforcements), trial_cache=self.cache.trial_cache(params),
                          progress=progress)
        self.cache.put(key, "optimize", int((time.perf_counter() - t0) * 1000), result.model_dump_json())
        self.cache.compute[key] = result
        return result

    def branch_result(self, branch_id: str) -> OptimizeResult:
        """A branch's engine result (the queue and phases; what diff and suggestions compare)."""
        b = self.inputs(branch_id)
        return self.compute(b.req, b.cands, b.ckey, b.reinforcements)

    def plan_years(self, b: BranchInputs, result: OptimizeResult, view_year: int | None = None,
                   progress=None, on_year=None) -> dict[str, YearResult]:
        """Every year of the plan (years.evaluate_years), cached like a run: the key adds the outages,
        the schedule and the reinforcements, which change the years but not the queue."""
        params = resolve_params(b.req)
        key = self.cache.key("years", params, b.ckey, extra=years_key(b))
        if key in self.cache.compute:
            if on_year:
                for y in self.cache.compute[key].values():
                    on_year(y)
            return self.cache.compute[key]
        cached = self.cache.get(key)
        if cached is not None:
            years = {k: YearResult.model_validate(v) for k, v in json.loads(cached).items()}
            if on_year:  # a cached plan still reaches the caller year by year, the same way
                for y in years.values():
                    on_year(y)
        else:
            t0 = time.perf_counter()
            years = evaluate_years(result, b.cands, params, scheduled=b.schedule, outages=b.outages,
                                   reinforcements=b.reinforcements, view_year=view_year,
                                   progress=progress, on_year=on_year)
            self.cache.put(key, "years", int((time.perf_counter() - t0) * 1000),
                           json.dumps({k: v.model_dump() for k, v in years.items()}))
        self.cache.compute[key] = years
        return years

    def result_with_years(self, b: BranchInputs) -> OptimizeResult:
        """A branch's engine result with every plan year attached (both through the caches)."""
        result = self.compute(b.req, b.cands, b.ckey, b.reinforcements)
        return result.model_copy(update={"years": self.plan_years(b, result)})

    def works_on_plan(self, plan: BranchInputs, result: OptimizeResult, outages: list[Outage]) -> list[OutageStudy]:
        """Another branch's planned windows studied on this plan's energised network (its projects,
        schedule, parameters and reinforcements; the windows' own repowers apply after them), so the
        diff can tell what the branch's projects do to each window. Only the years with a window are
        solved, without the N-1 screens (the verdict does not depend on them): per year one intact
        solve pair plus the window study and its curtailment search. Cached like the years: the key
        is this plan's years key with the outages swapped for the windows studied."""
        if not outages:
            return []
        params = resolve_params(plan.req)
        on = plan._replace(outages=list(outages))
        key = self.cache.key("works", params, on.ckey, extra=years_key(on))
        if key in self.cache.compute:
            return self.cache.compute[key]
        cached = self.cache.get(key)
        if cached is not None:
            studies = [OutageStudy.model_validate(x) for x in json.loads(cached)]
        else:
            t0 = time.perf_counter()
            in_service = energisation_years(result, plan.schedule)
            studies = [
                s
                for y in sorted({o.year for o in outages})
                for s in evaluate_year(y, plan.cands, params, in_service, outages=on.outages,
                                       reinforcements=plan.reinforcements, n1=False).outage_studies
            ]
            self.cache.put(key, "works", int((time.perf_counter() - t0) * 1000),
                           json.dumps([s.model_dump() for s in studies]))
        self.cache.compute[key] = studies
        return studies

    def diff(self, head_id: str, base_id: str) -> ConsequenceDiff:
        """The consequence diff of a branch against its base: the queue and phases, every plan year,
        and each of the branch's planned windows against the same window on the base's plan."""
        head_in, base_in = self.inputs(head_id), self.inputs(base_id)
        head = self.result_with_years(head_in)
        base = self.result_with_years(base_in)
        works_on_base = self.works_on_plan(base_in, base, head_in.outages)
        return diff_results(base, head, works_on_base=works_on_base)

    def suggestions(self, branch_id: str, limit: int, request_id: str | None = None) -> list[Suggestion]:
        """`suggest_unblock` for a branch (optionally for one deferred project), through the same two
        cache layers (it costs dozens of solves). Trialled on the branch's reinforced network."""
        b = self.inputs(branch_id)
        params = resolve_params(b.req)
        base = self.compute(b.req, b.cands, b.ckey, b.reinforcements)
        key = self.cache.key("suggest", params, b.ckey, extra=f"{limit}|{request_id}|{reinf_key(b.reinforcements)}")
        if key in self.cache.compute:
            return self.cache.compute[key]
        cached = self.cache.get(key)
        if cached is not None:
            self.cache.compute[key] = [Suggestion.model_validate(x) for x in json.loads(cached)]
            return self.cache.compute[key]
        t0 = time.perf_counter()
        sugs = suggest_unblock(b.cands, params, base=base, max_suggestions=limit, request_id=request_id,
                               net_factory=reinforced_factory(b.reinforcements))
        self.cache.put(key, "suggest", int((time.perf_counter() - t0) * 1000), json.dumps([x.model_dump() for x in sugs]))
        self.cache.compute[key] = sugs
        return sugs

    def _enrich(self, result: OptimizeResult, branch_id: str, b: BranchInputs) -> dict:
        """The engine result shaped for the map: coordinates, applicant, the operator's schedule
        against the recommendation, each phase's generators, and what the run studied."""
        out = result.model_dump()
        coords = self.warehouse.bus_coords()
        with self.store.cursor() as con:
            rows_by_id = {r["request_id"]: r for r in repository.candidate_rows(con, branch_id)}
        for q in out["queue"]:
            bid = q["bus_id"]
            q["lon"], q["lat"] = coords.get(int(bid), (None, None)) if bid is not None else (None, None)
            row = rows_by_id.get(q["request_id"], {})
            q["applicant"] = row.get("applicant") or ""
            q["import_mw"] = row.get("import_mw")
            # the operator's chosen energisation year (persisted on the branch) vs the optimizer's
            # recommendation: earlier than recommended, or scheduling a project the grid can't host,
            # goes against the recommendation and is flagged.
            sy = row.get("scheduled_year")
            q["scheduled_year"] = None if sy is None else int(sy)
            rec = q.get("recommended_year")
            q["against_recommendation"] = q["scheduled_year"] is not None and (
                rec is None or q["scheduled_year"] < rec)

        queue_by_id = {q["request_id"]: q for q in out["queue"]}
        for phase in out["phases"].values():
            gens = []
            for rid in phase["accepted"]:
                qi = queue_by_id.get(rid)
                if qi and qi.get("lon") is not None:
                    gens.append({
                        "request_id": rid, "bus_id": qi["bus_id"], "lon": qi["lon"], "lat": qi["lat"],
                        "rating_mw": qi["rating_mw"], "technology": qi["technology"],
                    })
            phase["generators"] = gens
        out["years"] = {}
        out["years_total"] = len(PLAN_YEARS)
        out["studied"] = {  # what this result covers, so the planner can tell when it is out of date
            "outage_ids": [o.outage_id for o in b.outages],
            "reinforcements": [r.model_dump() for r in b.reinforcements],
            "schedule": b.schedule,
        }
        out["snapshot_id"] = self.warehouse.baseline_id()
        out["branch_id"] = branch_id
        out["justification"] = ""
        return out

    def optimize_payload(self, body: OptimizeRequest, branch_id: str = "main", progress=None,
                         publish=None, view_year: int | None = None) -> dict:
        """Run a branch and enrich the result for the map, then solve every year of the plan.

        The greedy run decides the queue (progress 0..0.5); the years follow (0.5..0.95), the viewed
        year first. `publish(payload)` receives the partial payload as soon as the queue is known and
        again as each year lands, so the planner shows results while the rest are still solving.
        """
        report = progress or (lambda _s, _f: None)
        b = self.inputs(branch_id)._replace(req=body)
        params = resolve_params(body)
        key = self.cache.key("payload", params, b.ckey, extra=f"{body.with_justification}|{years_key(b)}")
        if key in self.cache.payload:
            return self.cache.payload[key]

        # the engine's own "done" means the queue is decided; the years are still to come
        result = self.compute(body, b.cands, b.ckey, b.reinforcements,
                              progress=lambda s, f: report("queue decided" if s == "done" else s, 0.5 * f))
        out = self._enrich(result, branch_id, b)
        if publish:
            publish(dict(out))

        def on_year(yr: YearResult) -> None:
            out["years"] = {**out["years"], str(yr.year): yr.model_dump()}
            if publish:
                publish(dict(out))

        years = self.plan_years(b, result, view_year, progress=lambda s, f: report(s, 0.5 + 0.45 * f),
                                on_year=on_year)
        out["years"] = {k: v.model_dump() for k, v in years.items()}
        if body.with_justification and result.queue:  # nothing queued (main today): nothing to narrate
            report("narration", 0.95)
            out["justification"] = narration.safely(self.narrator.justify, narration.summarize_queue(result))

        self.cache.payload[key] = out
        return out
