"""NGED's supply points: everything the NGED builder (`nged.py`), the half-hourly mapping (`nged_flows.py`) and the
pipeline need that belongs to one Grid Supply Point, in one record (`SupplyPoint`).

The machinery reads any supply point's LTDS tables the same way; what differs is here: the names each NGED dataset
files it under, the published figures the build scales to (NESO's GSP peak, the supergrid transformers' limits), and
the named exceptions the half-hourly check found (a demand row Removed in error, generators on their own feeders, a
connected site newer than the LTDS, an unmeasured load held at 0, the year shapes' reference columns). Each exception
is evidence for one supply point, never a rule: another supply point starts with none and earns its own the same way.

A supply point with no published peak cannot be built: `SupplyPoint.require_peak` raises, so demand is never scaled to
another supply point's figure. Bicker Fen's record holds today's values and is the default. Supported by NGED Open Data.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .cim import CgmesMeta
from .nged_runs import CATALOGUE as _BF_RUNS


@dataclass(frozen=True)
class SupplyPoint:
    """One NGED Grid Supply Point: where its data is filed, the published figures it is built to, and its exceptions."""

    key: str  # short id ("bicker-fen")
    source_id: str  # the GridSource's id
    source_name: str  # the GridSource's name
    gsp_name: str  # on the net and in breach messages ("Bicker Fen GSP")
    place: str  # the fallback place in the registry's labels
    net_name: str  # the pandapower net's name
    ltds_group: str  # LTDS "GSP Group" (Tables 1-4, nodes)
    table5_group: str  # LTDS Table 5's spelling of the same group
    ecr_gsp: str  # the ECR's `grid_supply_point`
    flows_gsp: str  # the bus mapping's and the loading files' name
    flows_resources: dict  # year -> (substation loading, branch loading) resource ids
    neso_gsp: str  # NESO's GSP id in the FES regional breakdown
    td_limits_resource: str  # the supergrid transformers' "Td Limits" resource (asset-limits package)
    peak_demand_mw: float | None  # NESO's published winter-peak demand at the GSP today; None: cannot be built
    boundary: dict  # the supergrid transformers' published limits
    center: tuple[float, float]  # (lon, lat): the map's fallback spot
    osm_bbox: tuple[float, float, float, float]  # south, west, north, east: where OSM substations are searched
    infeed_node: str  # the LTDS busbar of the published infeed site (Td Limits names the site and its SGT bays, not LTDS nodes)
    cgmes: CgmesMeta
    transmission_projects: tuple = ()
    removed_in_error: dict = field(default_factory=dict)  # LTDS node -> evidence
    generation_sites: tuple = ()
    ecr_additions: tuple = ()
    held_at_zero: dict = field(default_factory=dict)  # LTDS node -> why its cluster's injection is held at 0
    bsp_aliases: dict = field(default_factory=dict)  # a BSP group name Table 3 files its own rows under -> the name its primaries use
    normally_open: dict = field(default_factory=dict)  # (LTDS node, LTDS node) of a circuit run open -> its evidence
    year_shapes: dict = field(default_factory=dict)  # kind -> (branch columns, sign, capacity MW)
    run_catalogue: object | None = None  # runs.RunCatalogue, or None while it has no runs

    def require_peak(self) -> float:
        """NESO's winter-peak demand at this GSP, which the build scales today's demand to. Fails loudly when absent:
        never another supply point's figure."""
        if self.peak_demand_mw is None or not self.peak_demand_mw > 0:
            raise ValueError(f"{self.gsp_name} has no published supply-point peak (SupplyPoint.peak_demand_mw): "
                             f"its demand cannot be scaled, and another supply point's figure is never borrowed")
        return float(self.peak_demand_mw)


# ---- Bicker Fen ------------------------------------------------------------------------------------------------
_BF_CENTER = (-0.20, 52.88)  # Bicker Fen, Lincolnshire (lon, lat) — fallback spot for unplaceable buses
# Bicker Fen's own demand at the time of the GB winter peak (17:00-18:00 on a winter weekday): NESO
# "Regional Breakdown of 2024 FES: Demand (Active Power)" (NESO Data Portal, resource
# 7bd643c0-6aad-41ac-aa59-92b68992d9a4), GSP BICF_1, DemandPk summed over its demand types for fiscal
# year 2024/25 (the ~2024 baseline the growth anchors use): 150.491 MW (Electric Engagement), 150.249
# (Hydrogen Evolution), 146.965 (Holistic Transition). Today's demand is the same whatever the
# pathway, so we take the mean. The winter-peak power flow's demand sums to this today (nged._coincidence).
_BF_PEAK_DEMAND_MW = 149.235
# --- the GSP boundary: what sits above/outside this distribution network ----------------------
# Bicker Fen GSP is fed by two 400/132 kV supergrid transformers (SGTs). NGED's "Bicker Fen Td
# Limits" (Connected Data Portal, dataset asset-limits-pre-event-transmission-distribution-limits,
# resource 288e7abd-a45d-4592-b257-064d85d99d8b) gives each SGT an export limit of 263.5 MW in every
# season, and an import limit per NGED season: 160.1 MW winter, 179.1 MW intermediate cool and warm, 110.8 MW summer
# (published as given, though an intermediate limit above the winter one is unusual). The sign convention isn't
# documented; we read "export" as distribution → transmission, as the name and this net-exporting
# region suggest. We enforce the INTACT limit (both SGTs); the firm figure (one SGT out) is kept as context.
_BF_BOUNDARY = {
    "gsp_name": "Bicker Fen GSP",
    "sgt_count": 2,
    "export_limit_mw": 2 * 263.5,       # intact: both SGTs in service
    "firm_export_mw": 263.5,            # one SGT out
    # both SGTs, per season (config.RATING_SEASON_BY_MONTH); each planning case checks import against its season's
    "import_limit_mw": {"winter": 2 * 160.1, "intermediate_cool": 2 * 179.1, "intermediate_warm": 2 * 179.1, "summer": 2 * 110.8},
    "source": "NGED Connected Data Portal — Bicker Fen Td Limits (resource 288e7abd-a45d-4592-b257-064d85d99d8b)",
}
# Transmission-registered projects at Bicker Fen (NESO TEC + Interconnector registers, Sep 2026).
# `at` = where they connect. Ones not yet built that connect at the GSP's 132 kV ("gsp_132kv") would
# flow up through our SGTs, so — like every project that doesn't exist today — they're OPTIONAL
# registry projects (see nged.tec_candidates), never pre-loaded. The 400 kV ones bypass this network
# entirely but compete for the same transmission capacity out of Lincolnshire: context only.
_BF_LTDS_GROUP = "Bicker Fen 132kV"  # the LTDS "GSP Group" of every row in the bundled tables
_BF_TRANSMISSION_PROJECTS = [
    {"name": "Viking Link (HVDC interconnector to Denmark)", "mw": 1500, "type": "Interconnector",
     "status": "Built", "year": 2023, "at": "400kv", "source": "NESO Interconnector Register"},
    {"name": "Triton Knoll offshore wind", "mw": 824, "type": "Offshore wind",
     "status": "Built", "year": 2022, "at": "400kv", "source": "NESO TEC Register; tritonknoll.co.uk"},
    {"name": "Bicker Fen 1 Solar", "mw": 57, "type": "Solar + storage",
     "status": "Awaiting consents", "year": 2025, "at": "400kv", "source": "NESO TEC Register"},
    {"name": "Bicker Fen 2 Solar", "mw": 57, "type": "Solar + storage",
     "status": "Awaiting consents", "year": 2026, "at": "400kv", "source": "NESO TEC Register"},
    {"name": "Heckington Fen Solar Park", "mw": 400, "type": "Solar + storage",
     "status": "Scoping", "year": 2028, "at": "400kv", "source": "NESO TEC Register"},
    {"name": "Bicker Fenn Energy Park", "mw": 600, "type": "Solar + storage",
     "status": "Scoping", "year": 2029, "at": "400kv", "source": "NESO TEC Register"},
    {"name": "Temple Oaks Renewable Energy Park", "mw": 240, "type": "Solar + storage",
     "status": "Awaiting consents", "year": 2033, "at": "gsp_132kv", "source": "NESO TEC Register (embedded, site 'Bicker Fen GSP')"},
]
# LTDS Table 3 demand rows marked Removed that the rest of NGED's data shows are live, by node, each with its evidence
# (README register: "Warth Lane demand"). Kept in today's network; a named exception, never a general rule.
_BF_REMOVED_IN_ERROR = {
    "WALN5_MAIN1": "Warth Lane: the same LTDS edition rebuilt its 11 kV board (transformer 3T0 Removed, 13T0 New, new "
                   "MAIN2/MAIN3 sections) and issued no replacement demand row, while its 5 MW of solar stays Connected; "
                   "NGED's 2024 half-hourly flows (5.8 to 18.9 MW) and DFES 2025 both carry the site. Most likely an "
                   "omission, not confirmed by NGED",
}
# LTDS Table 5 gives generation at a BSP's 33 kV busbar as one total per technology; the ECR names the connected sites
# behind it. A site whose name is an engine bus of the same name sits there; the rest of its Table 5 total stays at the
# busbar (README register: "Generators on their own feeders"). Explicit, never a name-matching rule. Keyed by the Table 5
# row (Bulk Supply Point, Fuel Type); `nodes` are the LTDS node codes of the site's own bus(es).
_ECR_NAMED = "ECR connected site whose name is the engine bus it sits on"
_BF_GENERATION_SITES: tuple[dict, ...] = (
    {"table5": ("Sleaford 33 kV S Stn", "Photovoltaic"), "site": "Land south of Gorse Lane", "mw": 38.39, "nodes": ("GRLN3_#1L5", "GRLN3_#2L5"), "evidence": _ECR_NAMED},
    {"table5": ("Sleaford 33 kV S Stn", "Photovoltaic"), "site": "Ermine farm", "mw": 25.65, "nodes": ("ERMF3_#2H0",), "evidence": _ECR_NAMED},
    {"table5": ("Sleaford 33 kV S Stn", "Photovoltaic"), "site": "White cross lane", "mw": 21.85, "nodes": ("WHCR3_#1L5",), "evidence": _ECR_NAMED},
    {"table5": ("Sleaford 33 kV S Stn", "Photovoltaic"), "site": "Grange farm, kirkby on bain", "mw": 7.12, "nodes": ("KBGF3_#1L5",), "evidence": _ECR_NAMED},
    {"table5": ("Sleaford 33 kV S Stn", "Photovoltaic"), "site": "Deepdale solar farm", "mw": 3.71, "nodes": ("DLEF3_#1L5",), "evidence": _ECR_NAMED},
    {"table5": ("Skegness 33 kV S Stn", "Photovoltaic"), "site": "Manor farm pv", "mw": 17.86, "nodes": ("MAII3_#1L5",),
     "evidence": _ECR_NAMED + "; connected 23 Feb 2024 per the ECR, though NGED's 2024 flows show its spur at 0 MW all year"},
    {"table5": ("Skegness 33 kV S Stn", "Photovoltaic"), "site": "Lincoln farm solar", "mw": 8.36, "nodes": ("LCFM3_#1L5",), "evidence": _ECR_NAMED},
    {"table5": ("Skegness 33 kV S Stn", "Onshore Wind"), "site": "Bambers farm", "mw": 9.12, "nodes": ("BAMB3_1L3",),
     "evidence": _ECR_NAMED + "; the ECR's point of connection is 11 kV behind a site transformer, not modelled"},
    {"table5": ("Skegness 33 kV S Stn", "Onshore Wind"), "site": "The hollies farm", "mw": 2.66, "nodes": ("HOWF3_2M3",),
     "evidence": _ECR_NAMED + "; the ECR's point of connection is 0.4 kV behind a site transformer, not modelled"},
    {"table5": ("Grantham 33 kV S Stn", "Photovoltaic"), "site": "Mill farm solar", "mw": 4.28, "nodes": ("MLFM3_#1L5",), "evidence": _ECR_NAMED},
    # Table 5 counts this site as "Other Generation"; the ECR's own row says electrochemical storage, so it runs as a battery.
    # Its charging is the LTDS demand row already at this bus (5.35 MW): the battery's own import is 0, never both.
    {"table5": ("Grantham 33 kV S Stn", "Other Generation"), "site": "Mill farm battery storage", "mw": 6.65, "nodes": ("MILF3_#2H0",),
     "tech": "battery", "fuel": "Battery storage", "import_mw": 0.0, "evidence": _ECR_NAMED + "; ECR technology: Storage - Electrochemical (Batteries)"},
)

# Connected ECR sites that this LTDS edition predates (README register: "Connected sites missing from LTDS Table 5").
# Rule: a 132 kV site with no published connection point sits at the nearest 132 kV substation busbar by its published
# coordinates, when that busbar's OpenStreetMap position is within 3 km.
_BF_ECR_ADDITIONS: tuple[dict, ...] = (
    {"site": "Land at ash farm, vicarage drove", "mw": 48.38255, "tech": "solar", "fuel": "Photovoltaic", "node": "BICF1_MAIN1",
     "evidence": "ECR Connected 11 Jul 2025 at 132 kV, no connection point published; 0.33 km from Bicker Fen substation (OSM)"},
)
# how the CIM export names this model: its authority and regions (cim.CgmesMeta)
_BF_CGMES = CgmesMeta(authority_uri="http://gridify.example/nged-bickerfen", region_name="Great Britain", region_key="GB",
                            subregion_name="NGED East Midlands licence area", subregion_key="NGED")

# the half-hourly mapping (nged_flows): a new connection's 2024 shape per kind (README register: "Year shape"): NGED
# branch columns summed, the sign that makes export positive, and the capacity that makes them per unit
_BF_YEAR_SHAPES = {
    "solar": (("476901_427904_0_L1", "476902_427916_0_L1"), +1, 38.39),  # Land south of Gorse Lane, 38.39 MW (ECR)
    "wind_offshore": (("464902_439105_0_L1", "464904_439102_0_L1"), -1, 180.0),  # Skegness-Middlemarsh: Lynn and Inner Dowsing, 180 MW (LTDS Table 5)
    "wind_onshore": (("467501_46751_0_L1",), +1, 9.12),  # Bambers Farm, 9.12 MW (ECR)
}
# clusters whose injection is held at 0 by the owner's decision (README register), by an LTDS node code they contain
_BF_HELD_AT_ZERO = {"GRNO8_MAIN1": "the Grantham North 25 kV railway feeder (owner's decision: unmeasured load held at 0)"}

BICKER_FEN = SupplyPoint(
    key="bicker-fen",
    source_id="nged-bickerfen",
    source_name="NGED Bicker Fen 132 kV GSP",
    gsp_name=_BF_BOUNDARY["gsp_name"],
    place="Bicker Fen",
    net_name="NGED Bicker Fen 132kV (LTDS)",
    ltds_group=_BF_LTDS_GROUP,
    table5_group="Bicker Fen 132 kV S Stn",
    ecr_gsp="Bicker Fen 132Kv S Stn",
    flows_gsp="Bicker Fen",
    flows_resources={  # NGED curtailment-analysis data: "Bicker Fen Substation Load" / "Branch Load" (2024, file ID 319),
        2024: ("c95d6700-9728-42b3-ac99-f8762b17954c", "d82aeab2-25f2-4157-98ac-ae0412a8b97d"),
        2025: ("4fdb16c8-c94b-4a98-8166-f06607cce1bb", "02482039-6109-4fc9-af13-07742b73f65c"),  # "2025 Connected Export (ID 1124)"
    },
    neso_gsp="BICF_1",
    td_limits_resource="288e7abd-a45d-4592-b257-064d85d99d8b",
    peak_demand_mw=_BF_PEAK_DEMAND_MW,
    boundary=_BF_BOUNDARY,
    center=_BF_CENTER,
    osm_bbox=(52.6, -0.9, 53.45, 0.45),
    infeed_node="BICF1_MAIN1",  # Bicker Fen 132 kV main busbar: the SGTs land at bays BICF1_#180, #280 (Td Limits)
    cgmes=_BF_CGMES,
    transmission_projects=tuple(_BF_TRANSMISSION_PROJECTS),
    removed_in_error=_BF_REMOVED_IN_ERROR,
    generation_sites=_BF_GENERATION_SITES,
    ecr_additions=_BF_ECR_ADDITIONS,
    held_at_zero=_BF_HELD_AT_ZERO,
    year_shapes=_BF_YEAR_SHAPES,
    run_catalogue=_BF_RUNS,
)


# ---- Staythorpe (Step 4: the second supply point) ---------------------------------------------------------------
# README register "Staythorpe's snapshot (Step 4, Stage B)". Its tables are not bundled: the pipeline's manual asset
# `staythorpe_snapshot` fetches them into the git-ignored warehouse. It starts with NO exceptions: each must be earned by
# the half-hourly check, with a published row behind it, as Bicker Fen's were.
# NOT NESO's STAY_1 (Regional Breakdown of 2024 FES, resource 7bd643c0-6aad-41ac-aa59-92b68992d9a4: 263.580 HE,
# 262.331 EE, 257.595 HT, mean 261.169 MW): that is 1.50 times this group's 173.6 MW of coincident maxima, a coincidence
# above 1, so it does not describe this LTDS group and the build refuses it. In its place (README register
# "Staythorpe's supply-point peak: NGED's metered flows, not NESO"), a different kind of figure: the coincident maximum
# of the group's metered 11 kV primary demand in NGED's own half-hourly files, 2024 and 2025: 147.82 MW, 8 January 2025
# 17:30. The method reads Bicker Fen at 95-96% of NESO's figure (docs/reports/staythorpe-2026-11-13/metered_peak.py).
_ST_PEAK_DEMAND_MW = 147.82
# NGED "Staythorpe Td Limits" (resource 52709698-d63f-4e3e-bdc0-082c838f5d18), two SGTs (S1, S2) with the same figures:
# export 578.2 MW every season; import 208.3 MW winter, 185.0 MW intermediate cool and warm, 95.9 MW summer, per SGT.
_ST_BOUNDARY = {
    "gsp_name": "Staythorpe GSP",
    "sgt_count": 2,
    "export_limit_mw": 2 * 578.2,
    "firm_export_mw": 578.2,
    "import_limit_mw": {"winter": 2 * 208.3, "intermediate_cool": 2 * 185.0, "intermediate_warm": 2 * 185.0, "summer": 2 * 95.9},
    "source": "NGED Connected Data Portal — Staythorpe Td Limits (resource 52709698-d63f-4e3e-bdc0-082c838f5d18)",
}

STAYTHORPE = SupplyPoint(
    key="staythorpe",
    source_id="nged-staythorpe",
    source_name="NGED Staythorpe 132 kV GSP",
    gsp_name=_ST_BOUNDARY["gsp_name"],
    place="Staythorpe",
    net_name="NGED Staythorpe 132kV (LTDS)",
    ltds_group="Staythorpe 132kV",
    table5_group="Staythorpe  C  132 kV S Stn",  # as NGED's Table 5 spells it (two spaces either side of C)
    ecr_gsp="Staythorpe  C  132Kv S Stn",  # as the ECR spells it
    flows_gsp="Staythorpe",
    flows_resources={
        2024: ("aef22f8e-19df-4101-b54c-c1710971f505", "3d9ab33b-cd17-4683-a3bb-40607dfba1a6"),  # "Staythorpe Substation Load" / "Branch Load"
        2025: ("b5733c69-283a-4820-8d2d-cd3628de31f1", "2cc32ecf-198f-471e-bbf9-f59e4b91d876"),  # "Staythorpe - 2025 Connected Export (ID 1132)"
    },
    neso_gsp="STAY_1",
    td_limits_resource="52709698-d63f-4e3e-bdc0-082c838f5d18",
    peak_demand_mw=_ST_PEAK_DEMAND_MW,
    boundary=_ST_BOUNDARY,
    center=(-0.839, 53.142),  # the mean of its 117 published ECR site coordinates (a map fallback only)
    osm_bbox=(52.67, -1.14, 53.54, -0.51),  # their extent, 0.1 degree margin
    infeed_node="STAY1_MAIN1",  # Staythorpe C 132 kV main busbar: the SGTs land at bays STAY1_#180, #280 (Td Limits)
    # README register "Staythorpe: Hawton's BSP rows are an aggregate": Table 3 files Hawton's 132/33 kV group rows as
    # "Hawton SOP (GT1)/(GT2)" (Primary "-", 38.4 + 38.4 MW at Hawton's own 33 kV bars HAWT3_MAIN1/2) while its primaries
    # are filed under "Hawton"; 76.8 MW against the primaries' 81.6 MW (94%), every other BSP aggregate's pattern. Counted
    # as demand they put Hawton's 45 MVA transformers at 170% in 2026 (Step 4, Stage C).
    bsp_aliases={"Hawton SOP": "Hawton"},
    # README register "Staythorpe: the Ranskill-Daneshill Road normally-open point": four branches of the path read 0.000 MW
    # on every half-hour of 2025 in NGED's branch file; the circuit leaving the Daneshill Road ACR (its only remotely
    # operable switch) is opened. Inferred from NGED's half-hourly flows, not an LTDS row.
    normally_open={("RANS3_1L5", "89ZGWMA5"): "NGED 2025 branch flows: Ranskill-Daneshill Road path at 0.000 MW all year"},
    cgmes=CgmesMeta(authority_uri="http://gridify.example/nged-staythorpe", region_name="Great Britain", region_key="GB",
                    subregion_name="NGED East Midlands licence area", subregion_key="NGED"),
)

SUPPLY_POINTS = {p.key: p for p in (BICKER_FEN, STAYTHORPE)}
