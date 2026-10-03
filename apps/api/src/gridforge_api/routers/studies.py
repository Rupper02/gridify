"""The study catalogue over HTTP: what the engine can analyse on a plan, and running one as a job."""

from fastapi import APIRouter, HTTPException
from pydantic import ValidationError

from gridforge_optimizer import STUDIES

from .. import repository
from ..deps import jobs, plans, scenarios

router = APIRouter()


@router.get("/studies")
def study_catalogue() -> dict:
    """Every study in `studies.STUDIES`: its description, parameter schema, whether it reads the plan, and
    an estimated cost in power-flow solves at its default parameters (the agents see the same catalogue as tools)."""
    out = []
    for kind, spec in STUDIES.items():
        defaults = spec.params_model()
        out.append({"kind": kind, "description": spec.description, "needs_plan": spec.needs_plan,
                    "params_schema": spec.params_model.model_json_schema(), "cost_hint_solves": spec.cost_hint(defaults)})
    return {"studies": out}


@router.post("/branches/{branch_id}/studies/{kind}")
def start_study(branch_id: str, kind: str, params: dict | None = None) -> dict:
    """Run a study on a branch's plan as a background job (poll GET /jobs/{id}); the result is a
    `StudyResult`, cached by the branch's inputs and the parameters. 404 unknown branch or study,
    422 bad parameters or a plan-reading study on a branch that has not run."""
    if kind not in STUDIES:
        raise HTTPException(status_code=404, detail=f"study '{kind}' is not in the catalogue: {', '.join(STUDIES)}")
    with scenarios.cursor() as con:
        repository.require_branch(con, branch_id)
    try:
        p = STUDIES[kind].params_model.model_validate(params or {})
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors()) from None
    if STUDIES[kind].needs_plan and not plans.freshness(branch_id).fresh:
        raise HTTPException(status_code=422, detail=f"{kind} reads the plan years: run the branch first")
    return jobs.start("study", lambda progress, _publish: plans.study(branch_id, kind, p, progress=progress).model_dump())
