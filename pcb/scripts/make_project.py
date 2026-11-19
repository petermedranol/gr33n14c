#!/usr/bin/env python
"""Scaffold a blank KiCad project (pro + sch + pcb) using the bundled pcbnew.

Run with KiCad's bundled Python:
    & "C:\\Program Files\\KiCad\\10.0\\bin\\python.exe" make_project.py <out_dir> <name>
"""
import json
import os
import sys
import uuid

import pcbnew


def write_pcb(path: str) -> None:
    """Create an empty board and save it so the file matches this KiCad version."""
    board = pcbnew.BOARD()
    pcbnew.SaveBoard(path, board)


def write_sch(path: str, project_uuid: str) -> None:
    """Minimal empty schematic for KiCad 10."""
    content = f"""(kicad_sch
\t(version 20250114)
\t(generator "eeschema")
\t(generator_version "10.0")
\t(uuid "{project_uuid}")
\t(paper "A4")
\t(lib_symbols)
\t(sheet_instances
\t\t(path "/"
\t\t\t(page "1")
\t\t)
\t)
)
"""
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


def write_pro(path: str, name: str) -> None:
    """Minimal project file. KiCad fills in the rest on first open."""
    pro = {
        "board": {"design_settings": {}, "layer_presets": [], "viewports": []},
        "boards": [],
        "cvpcb": {"equivalence_files": []},
        "libraries": {"pinned_footprint_libs": [], "pinned_symbol_libs": []},
        "meta": {"filename": f"{name}.kicad_pro", "version": 1},
        "net_settings": {
            "classes": [
                {
                    "name": "Default",
                    "clearance": 0.2,
                    "track_width": 0.25,
                    "via_diameter": 0.8,
                    "via_drill": 0.4,
                }
            ]
        },
        "pcbnew": {"page_layout_descr_file": ""},
        "schematic": {"legacy_lib_list": []},
        "sheets": [],
        "text_variables": {},
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(pro, fh, indent=2)


def main() -> None:
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "."
    name = sys.argv[2] if len(sys.argv) > 2 else "project"
    os.makedirs(out_dir, exist_ok=True)

    base = os.path.join(out_dir, name)
    project_uuid = str(uuid.uuid4())

    write_pcb(base + ".kicad_pcb")
    write_sch(base + ".kicad_sch", project_uuid)
    write_pro(base + ".kicad_pro", name)

    print(f"KiCad project created in: {out_dir}")
    print(f"  {name}.kicad_pro")
    print(f"  {name}.kicad_sch")
    print(f"  {name}.kicad_pcb")
    print(f"pcbnew {pcbnew.GetBuildVersion()}")


if __name__ == "__main__":
    main()
