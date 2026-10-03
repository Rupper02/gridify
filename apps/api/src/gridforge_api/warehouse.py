"""The pipeline warehouse, read-only: the geolocated grid, the registry and the snapshot history."""

from pathlib import Path

import duckdb


class Warehouse:
    """Read-only access to the pipeline's DuckDB warehouse. Nothing here ever writes."""

    def __init__(self, path: Path):
        self.path = path

    def exists(self) -> bool:
        return self.path.exists()

    def query(self, sql: str, params: list | None = None) -> list[dict]:
        """Run a read-only SQL query and return rows as dicts."""
        con = duckdb.connect(str(self.path), read_only=True)
        try:
            cur = con.execute(sql, params or [])
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
        finally:
            con.close()

    def table_exists(self, name: str) -> bool:
        return bool(self.query("SELECT 1 FROM information_schema.tables WHERE table_name = ?", [name]))

    def baseline_id(self) -> str:
        """The latest model snapshot's content-hash id (used to key the result caches)."""
        rows = self.query("SELECT snapshot_id FROM snapshots ORDER BY created_at DESC LIMIT 1")
        return rows[0]["snapshot_id"] if rows else "baseline"

    def baseline_model(self) -> dict:
        """The geolocated grid (buses, lines, transformers, loads) for the map."""
        buses = self.query("SELECT bus_id, name, vn_kv, lon, lat FROM buses WHERE lon IS NOT NULL")
        lines = self.query(
            """
            SELECT l.line_id, l.line_name, l.rating_a, l.voltage_kv, l.from_bus, l.to_bus,
                   f.lon AS from_lon, f.lat AS from_lat, t.lon AS to_lon, t.lat AS to_lat
            FROM lines l
            JOIN buses f ON l.from_bus = f.bus_id
            JOIN buses t ON l.to_bus   = t.bus_id
            WHERE f.lon IS NOT NULL AND t.lon IS NOT NULL
            """
        )
        transformers = self.query(
            """
            SELECT tr.trafo_id, tr.name, tr.sn_mva, tr.hv_bus, tr.lv_bus,
                   h.vn_kv AS hv_kv, lv.vn_kv AS lv_kv, h.name AS hv_name,
                   h.lon AS hv_lon, h.lat AS hv_lat, lv.lon AS lv_lon, lv.lat AS lv_lat
            FROM transformers tr
            JOIN buses h  ON tr.hv_bus = h.bus_id
            JOIN buses lv ON tr.lv_bus = lv.bus_id
            WHERE h.lon IS NOT NULL AND lv.lon IS NOT NULL
            """
        )
        try:
            loads = self.query(
                """
                SELECT ld.bus_id, ld.p_mw, ld.region_id, b.lon, b.lat
                FROM loads ld
                JOIN buses b ON ld.bus_id = b.bus_id
                WHERE b.lon IS NOT NULL
                """
            )
        except Exception:  # warehouse predates the demand regions
            loads = self.query(
                """
                SELECT ld.bus_id, ld.p_mw, b.lon, b.lat
                FROM loads ld
                JOIN buses b ON ld.bus_id = b.bus_id
                WHERE b.lon IS NOT NULL
                """
            )
        for i, ld in enumerate(loads):
            ld["load_id"] = i
        try:
            generators = self.query(
                """
                SELECT g.request_id, g.bus_id, g.rating_mw, g.technology, g.applicant, b.lon, b.lat
                FROM generators g JOIN buses b ON g.bus_id = b.bus_id
                WHERE b.lon IS NOT NULL
                """
            )
        except Exception:  # warehouse predates the existing-fleet table
            generators = []
        return {"buses": buses, "lines": lines, "transformers": transformers, "loads": loads,
                "generators": generators, "regions": self.regions()}

    def regions(self) -> list[dict]:
        """The demand groups (one per live LTDS Table 3 row), each with the buses its loads sit on.
        Empty for a warehouse that predates them (re-materialise the pipeline)."""
        if not self.table_exists("regions"):
            return []
        rows = self.query("SELECT * FROM regions ORDER BY region_id")
        buses: dict[str, set[int]] = {}
        for ld in self.query("SELECT region_id, bus_id FROM loads WHERE region_id IS NOT NULL"):
            buses.setdefault(ld["region_id"], set()).add(int(ld["bus_id"]))
        nan_to_none = lambda v: None if isinstance(v, float) and v != v else v  # noqa: E731 (JSON has no NaN)
        return [{**{k: nan_to_none(v) for k, v in r.items()}, "buses": sorted(buses.get(r["region_id"], ()))}
                for r in rows]

    def bus_coords(self) -> dict[int, tuple[float, float]]:
        """Map every geolocated bus id to its (lon, lat), for attaching coords to queue items."""
        return {
            int(b["bus_id"]): (b["lon"], b["lat"])
            for b in self.query("SELECT bus_id, lon, lat FROM buses WHERE lon IS NOT NULL")
        }

    def line_ids(self) -> set[str]:
        return {str(r["line_id"]) for r in self.query("SELECT line_id FROM lines")}

    def trafo_ids(self) -> set[str]:
        return {str(r["trafo_id"]) for r in self.query("SELECT trafo_id FROM transformers")}

    def generator_ids(self) -> set[str]:
        """The existing fleet's ids (EX-…), the targets of a generator maintenance window."""
        try:
            return {str(r["request_id"]) for r in self.query("SELECT request_id FROM generators")}
        except Exception:  # warehouse predates the existing-fleet table
            return set()

    def valid_bus_ids(self) -> set[int]:
        return {int(b["bus_id"]) for b in self.query("SELECT bus_id FROM buses")}

    def registry_rows(self) -> list[dict]:
        """The REGISTRY: the pool of projected connection projects, available to add to a branch.
        main does not auto-include these: you pull them onto a branch as they come along."""
        return self.query("SELECT * FROM candidate_projects")
