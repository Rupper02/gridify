"""Run the engine for a branch: resolve parameters, build candidates, cache, enrich for the map."""

import json
import time

from gridforge_optimizer import Candidate, OptimizeParams, OptimizeResult, Suggestion, optimize, suggest_unblock
from gridforge_optimizer.config import FORECASTS

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
    return OptimizeParams(
        growth_2030=growth_2030, growth_2035=growth_2035, scenario=scenario, **weights
    )


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

    def compute(self, body: OptimizeRequest, cands: list[Candidate], ckey: str, progress=None) -> OptimizeResult:
        """Run the deterministic optimizer for a request + candidate set.

        Three layers: the in-process dict, the durable `result_cache` table (survives restarts and is
        shared by every endpoint that needs the same run), then the engine. Keys include the model
        snapshot, the parameters, the candidate set and the engine's code fingerprint."""
        params = resolve_params(body)
        key = self.cache.key("optimize", params, ckey)
        if key in self.cache.compute:
            return self.cache.compute[key]
        cached = self.cache.get(key)
        if cached is not None:
            self.cache.compute[key] = OptimizeResult.model_validate_json(cached)
            return self.cache.compute[key]
        t0 = time.perf_counter()
        result = optimize(cands, params, trial_cache=self.cache.trial_cache(params), progress=progress)
        self.cache.put(key, "optimize", int((time.perf_counter() - t0) * 1000), result.model_dump_json())
        self.cache.compute[key] = result
        return result

    def suggestions(self, req: OptimizeRequest, cands: list[Candidate], ckey: str, limit: int) -> list[Suggestion]:
        """`suggest_unblock` for a branch, through the same two cache layers (it costs dozens of solves)."""
        params = resolve_params(req)
        base = self.compute(req, cands, ckey)
        key = self.cache.key("suggest", params, ckey, extra=str(limit))
        if key in self.cache.compute:
            return self.cache.compute[key]
        cached = self.cache.get(key)
        if cached is not None:
            self.cache.compute[key] = [Suggestion.model_validate(x) for x in json.loads(cached)]
            return self.cache.compute[key]
        t0 = time.perf_counter()
        sugs = suggest_unblock(cands, params, base=base, max_suggestions=limit)
        self.cache.put(key, "suggest", int((time.perf_counter() - t0) * 1000), json.dumps([x.model_dump() for x in sugs]))
        self.cache.compute[key] = sugs
        return sugs

    def optimize_payload(self, body: OptimizeRequest, branch_id: str = "main", progress=None) -> dict:
        """Run the optimizer for a branch and enrich the result for the map (coords, generators).

        Resolves the DFES scenario to growth, runs the deterministic engine (cached by inputs AND the
        branch's candidate set), then attaches map coordinates + applicant and, optionally, a narrative.
        """
        cands = self.candidates(branch_id)
        ckey = cand_key(cands)
        params = resolve_params(body)
        key = self.cache.key("payload", params, ckey, extra=str(body.with_justification))
        if key in self.cache.payload:
            return self.cache.payload[key]

        result = self.compute(body, cands, ckey, progress=progress)
        out = result.model_dump()

        coords = self.warehouse.bus_coords()
        with self.store.cursor() as con:
            rows_by_id = {r["request_id"]: r for r in repository.candidate_rows(con, branch_id)}
        for q in out["queue"]:
            bid = q["bus_id"]
            q["lon"], q["lat"] = coords.get(int(bid), (None, None)) if bid is not None else (None, None)
            row = rows_by_id.get(q["request_id"], {})
            q["applicant"] = row.get("applicant") or ""
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

        out["snapshot_id"] = self.warehouse.baseline_id()
        out["branch_id"] = branch_id
        out["justification"] = ""
        if body.with_justification:
            if progress:
                progress("narration", 0.95)
            out["justification"] = narration.safely(self.narrator.justify, narration.summarize_queue(result))

        self.cache.payload[key] = out
        return out
