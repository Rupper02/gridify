"""Projects: the grids GridForge plans on. One is built in (NGED Bicker Fen, read from the pipeline's
warehouse so the lineage is real); any number come from an import (a CGMES zip, a pandapower JSON, a
MATPOWER case), each with its own main branch, baseline and capabilities.

`Projects` is the one place the API reads a grid through: the per-project `GridSource`, the model
for the map, the element ids a proposal is checked against, the boundary card, the CIM export (the
read-through caches that used to sit in a router's module globals live here, per project and
baseline). Everything a user does still goes to the scenarios store; the warehouse stays read-only."""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from gridforge_optimizer import GridModel, ImportMeta, ModelAssumption
from gridforge_optimizer.cim import cgmes_zip_bytes, export_cgmes
from gridforge_optimizer.network import build_base_net, feasibility
from gridforge_optimizer.nged import NGED_CGMES_META, gsp_boundary
from gridforge_optimizer.sources import NgedSource, source_from_file, source_kind_for

from .config import MAX_IMPORT_BYTES, now
from .store import PROJECT_COLS, ScenarioStore, ensure_main_branch
from .warehouse import Warehouse

PROJECT_TABLES = ("project_events", "project_state", "agent_runs", "threads", "approvals", "agent_budgets", "reviews")  # keyed by project_id
BRANCH_TABLES = ("added_candidates", "branch_outages", "branch_reinforcements", "findings", "merges")  # keyed by branch_id


class WarehouseNgedSource:
    """NGED as the API sees it: the model, the registry and the snapshot id from the pipeline's
    warehouse (the lineage is real), the network, the boundary and the assumptions from the engine's builder."""

    kind = "nged"

    def __init__(self, project_id: str, warehouse: Warehouse):
        self.id = project_id
        self.name = "NGED Bicker Fen 132 kV GSP"
        self._warehouse = warehouse
        self._engine = NgedSource()
        self.cgmes_meta = NGED_CGMES_META

    def build_net(self):
        return build_base_net()

    def model(self) -> GridModel:
        return GridModel.model_validate(self._warehouse.baseline_model())

    def candidates(self) -> list[dict]:
        return self._warehouse.registry_rows()

    def boundary(self) -> dict | None:
        return gsp_boundary()

    def fingerprint(self) -> str:
        return self._warehouse.baseline_id()

    def assumptions(self) -> list[ModelAssumption]:
        return self._engine.assumptions()

    def capabilities(self) -> dict:
        return self._engine.capabilities()


class Projects:
    """The registry of projects, and the grid behind each (a `GridSource`), with per-baseline caches."""

    def __init__(self, store: ScenarioStore, warehouse: Warehouse, files_dir: Path, nged_id: str):
        self._store = store
        self._warehouse = warehouse
        self._files = files_dir
        self.nged_id = nged_id
        self._sources: dict[str, Any] = {}
        self._models: dict[tuple[str, str], GridModel] = {}
        self._boundaries: dict[tuple[str, str], dict | None] = {}
        self._cgmes: dict[tuple[str, str, str], bytes] = {}
        store.on_reset(self.forget)

    def forget(self) -> None:
        """Drop every in-process layer (the store was pointed elsewhere, or a project was deleted)."""
        self._sources.clear()
        self._models.clear()
        self._boundaries.clear()
        self._cgmes.clear()

    # --- rows -------------------------------------------------------------------------------------------
    def rows(self) -> list[dict]:
        with self._store.cursor() as con:
            cur = con.execute(f"SELECT {', '.join(PROJECT_COLS)} FROM projects ORDER BY (project_id = ?) DESC, created_at", [self.nged_id])
            return [dict(zip(PROJECT_COLS, r)) for r in cur.fetchall()]

    def row(self, pid: str) -> dict:
        with self._store.cursor() as con:
            r = con.execute(f"SELECT {', '.join(PROJECT_COLS)} FROM projects WHERE project_id = ?", [pid]).fetchone()
        if r is None:
            raise HTTPException(status_code=404, detail=f"project '{pid}' not found")
        return dict(zip(PROJECT_COLS, r))

    def main_id(self, pid: str) -> str:
        return self.row(pid)["main_id"]

    def to_client(self, row: dict) -> dict:
        pid = row["project_id"]
        return {
            "project_id": pid, "name": row["name"], "source_kind": row["source_kind"], "snapshot_id": self.baseline(pid),
            "created_at": row["created_at"], "main_id": row["main_id"], "builtin": pid == self.nged_id,
            "file_name": Path(row["source_ref"]).name if row.get("source_ref") else None,
            "meta": json.loads(row["meta_json"]) if row.get("meta_json") else None,
            "capabilities": json.loads(row["capabilities_json"]) if row.get("capabilities_json") else self.capabilities(pid),
            "report": json.loads(row["report_json"]) if row.get("report_json") else None,
        }

    # --- the grid behind a project ----------------------------------------------------------------------
    def source(self, pid: str):
        src = self._sources.get(pid)
        if src is None:
            if pid == self.nged_id:
                src = WarehouseNgedSource(pid, self._warehouse)
            else:
                row = self.row(pid)
                path = Path(row["source_ref"])
                if not path.exists():
                    raise HTTPException(status_code=410, detail=f"project '{pid}': its file {path.name} is gone from the server; import it again")
                meta = ImportMeta.model_validate_json(row["meta_json"]) if row.get("meta_json") else None
                src = source_from_file(path.name, path.read_bytes(), id=pid, name=row["name"], meta=meta)
            self._sources[pid] = src
        return src

    def baseline(self, pid: str) -> str:
        """The content identity results for this project are cached under (its snapshot or file fingerprint)."""
        return self.source(pid).fingerprint()

    def model(self, pid: str) -> GridModel:
        key = (pid, self.baseline(pid))
        if key not in self._models:
            self._models = {k: v for k, v in self._models.items() if k[0] != pid}  # one model per project
            self._models[key] = self.source(pid).model()
        return self._models[key]

    def model_dict(self, pid: str) -> dict:
        return self.model(pid).model_dump()

    def bus_coords(self, pid: str) -> dict[int, tuple[float, float]]:
        return {b.bus_id: (b.lon, b.lat) for b in self.model(pid).buses}

    def element_ids(self, pid: str) -> dict[str, set]:
        """What a proposal may name on this project: its buses, lines, transformers and existing generators."""
        m = self.model(pid)
        return {"buses": {b.bus_id for b in m.buses}, "lines": {str(ln.line_id) for ln in m.lines},
                "trafos": {str(t.trafo_id) for t in m.transformers}, "generators": {g.request_id for g in m.generators}}

    def registry_rows(self, pid: str) -> list[dict]:
        return self.source(pid).candidates()

    def capabilities(self, pid: str) -> dict:
        return self.source(pid).capabilities()

    def assumptions(self, pid: str) -> list[dict]:
        return [a.model_dump() for a in self.source(pid).assumptions()]

    def boundary(self, pid: str) -> dict | None:
        key = (pid, self.baseline(pid))
        if key not in self._boundaries:
            self._boundaries[key] = self.source(pid).boundary()
        return self._boundaries[key]

    def cgmes_zip(self, pid: str, engine: str) -> bytes:
        """The project's network as a CGMES exchange, per baseline and engine (the same bytes until one changes)."""
        key = (pid, self.baseline(pid), engine)
        if key not in self._cgmes:
            src = self.source(pid)
            net = src.build_net()
            feasibility(net)  # settle the tap changers so the SSH carries today's regulated steps
            meta = getattr(src, "cgmes_meta", None)
            files = export_cgmes(net, self.model(pid), key[1], **({"meta": meta} if meta else {}))
            self._cgmes = {key: cgmes_zip_bytes(files)}
        return self._cgmes[key]

    # --- import and delete ------------------------------------------------------------------------------
    def create(self, name: str, filename: str, data: bytes, meta: ImportMeta | None) -> dict:
        """Import a grid: read the file by its extension, validate it (422 with the report when the engine
        cannot plan on it), keep the file, seed the project's main branch."""
        try:
            kind = source_kind_for(filename)
        except ValueError as e:
            raise HTTPException(status_code=415, detail=str(e)) from None
        if len(data) > MAX_IMPORT_BYTES:
            raise HTTPException(status_code=413, detail=f"the file is {len(data) / 1e6:.0f} MB; the limit is {MAX_IMPORT_BYTES // (1024 * 1024)} MB")
        pid = "prj-" + uuid.uuid4().hex[:8]
        try:
            src = source_from_file(filename, data, id=pid, name=name, meta=meta)
        except Exception as e:  # a file the importer cannot read is the user's problem to see, not a 500
            raise HTTPException(status_code=422, detail={"code": "unreadable", "message": f"could not read the file as {kind}: {type(e).__name__}: {e}"}) from None
        report = src.validate()
        if not report.ok:
            raise HTTPException(status_code=422, detail={"code": "invalid", "message": "; ".join(report.errors), "report": report.model_dump()})
        folder = self._files / pid
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / Path(filename).name
        path.write_bytes(data)
        main_id = f"{pid}-main"
        row = {"project_id": pid, "name": name, "source_kind": kind, "source_ref": str(path), "snapshot_id": src.fingerprint(),
               "created_at": now(), "meta_json": meta.model_dump_json() if meta else None, "report_json": report.model_dump_json(),
               "capabilities_json": json.dumps(src.capabilities()), "main_id": main_id}
        with self._store.cursor() as con:
            con.execute(f"INSERT INTO projects ({', '.join(PROJECT_COLS)}) VALUES ({', '.join('?' * len(PROJECT_COLS))})", [row[c] for c in PROJECT_COLS])
            ensure_main_branch(con, main_id, pid)
        self._sources[pid] = src
        return self.to_client(row)

    def delete(self, pid: str) -> dict:
        """Remove an imported project: its branches and everything on them, its agent records, its cached
        results and its file. The built-in project stays."""
        row = self.row(pid)
        if pid == self.nged_id:
            raise HTTPException(status_code=409, detail="the built-in project cannot be deleted")
        with self._store.cursor() as con:
            bids = [r[0] for r in con.execute("SELECT branch_id FROM branches WHERE project_id = ?", [pid]).fetchall()]
            for table in BRANCH_TABLES:
                for bid in bids:
                    con.execute(f"DELETE FROM {table} WHERE branch_id = ?", [bid])
            tids = [r[0] for r in con.execute("SELECT thread_id FROM threads WHERE project_id = ?", [pid]).fetchall()]
            for tid in tids:
                con.execute("DELETE FROM messages WHERE thread_id = ?", [tid])
            for table in PROJECT_TABLES:
                con.execute(f"DELETE FROM {table} WHERE project_id = ?", [pid])
            con.execute("DELETE FROM branches WHERE project_id = ?", [pid])
            con.execute("DELETE FROM result_cache WHERE snapshot_id = ?", [row["snapshot_id"]])
            con.execute("DELETE FROM projects WHERE project_id = ?", [pid])
        shutil.rmtree(self._files / pid, ignore_errors=True)
        self.forget()
        return {"project_id": pid, "deleted": True, "branches_removed": len(bids)}
