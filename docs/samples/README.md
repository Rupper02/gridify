# Import samples

Two small grids to exercise the import path (the projects screen, *Import a grid*). Both are the IEEE 9-bus test system
as pandapower ships it (`pandapower.networks.case9`), with the one thing a real simulation needs that the case does not
say: each power station's technology (`thermal`). They are the same grid in the two formats GridForge reads:

| File | What it is |
|---|---|
| `ieee9.json` | The pandapower network as JSON (`pp.to_json`), costs and limits included |
| `ieee9-cgmes.zip` | The same network as GridForge's own CGMES 2.4.15 export (`gridforge_optimizer.cim.export_cgmes`): EQ, TP, SSH and GL profiles in one zip, the merit-order costs and the infeed's supply limit carried as `gridforge.*` description tags, which the import reads back |

What the form asks for, because the file cannot say it: a demand forecast (any growth on the year before, e.g. 1.01 for every
plan year), the N-1 floor (345 kV is the only level), the voltage limits at 345 kV (a preset fills them), and the summer data
(a minimum-demand share, e.g. 0.5, and a summer / winter line rating ratio, e.g. 0.9). Both import with no warnings: nine
buses, nine lines, three loads, two power stations and one external grid, both study cases.

Regenerate them with `pp.to_json` and `export_cgmes` on `case9` with `gen["type"] = "thermal"`; nothing else is edited.
