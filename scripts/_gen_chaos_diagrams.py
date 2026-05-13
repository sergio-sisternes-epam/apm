"""Generate the chaos-monkey drawio diagrams (3 pages).

Run from repo root:
  uv run --no-sync python scripts/_gen_chaos_diagrams.py

Emits docs/diagrams/chaos-monkey.drawio.

Pages:
  1. Discovery loop (sequence diagram)
  2. Regression-guard loop (sequence diagram)
  3. Composition (flowchart linking the two loops)

No external deps; pure stdlib XML emission.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from xml.dom import minidom

# --- helpers -----------------------------------------------------------

PARTICIPANT_W = 150
PARTICIPANT_H = 44
PARTICIPANT_SPACING = 180
HEADER_Y = 40
LIFELINE_START_Y = HEADER_Y + PARTICIPANT_H
MSG_STEP = 36
NOTE_W = 280
NOTE_H = 36


def _cell(root, cell_id, value, style, x, y, w, h, parent="1", vertex=True):
    c = ET.SubElement(
        root,
        "mxCell",
        {
            "id": cell_id,
            "value": value,
            "style": style,
            "vertex": "1" if vertex else "0",
            "parent": parent,
        },
    )
    ET.SubElement(
        c,
        "mxGeometry",
        {"x": str(x), "y": str(y), "width": str(w), "height": str(h), "as": "geometry"},
    )
    return c


def _build_page(diagram_name, participants, messages, notes):
    """Build a single diagram page.

    participants: list[(id, label, color)]
    messages: list[(from_idx, to_idx, label, kind)] where kind in
              {"sync", "return", "self"}
    notes: list[(y_step_idx, spanning_idxs, text)]
    """
    mx = ET.Element(
        "mxGraphModel",
        {
            "dx": "1422",
            "dy": "800",
            "grid": "1",
            "gridSize": "10",
            "guides": "1",
            "tooltips": "1",
            "connect": "1",
            "arrows": "1",
            "fold": "1",
            "page": "1",
            "pageScale": "1",
            "pageWidth": str(180 + PARTICIPANT_SPACING * (len(participants) + 1)),
            "pageHeight": "1400",
            "math": "0",
            "shadow": "0",
        },
    )
    root = ET.SubElement(mx, "root")
    ET.SubElement(root, "mxCell", {"id": "0"})
    ET.SubElement(root, "mxCell", {"id": "1", "parent": "0"})

    # title
    _cell(
        root,
        "title",
        f"<b>{diagram_name}</b>",
        "text;html=1;align=center;verticalAlign=middle;fontSize=18;fontStyle=1;",
        60,
        4,
        PARTICIPANT_SPACING * len(participants),
        28,
    )

    # participants + lifelines
    px = {}
    for i, (pid, label, color) in enumerate(participants):
        x = 60 + i * PARTICIPANT_SPACING
        px[pid] = x + PARTICIPANT_W // 2
        # header box
        _cell(
            root,
            f"p_{pid}",
            label,
            f"rounded=1;whiteSpace=wrap;html=1;fillColor={color};"
            "strokeColor=#333333;fontSize=12;fontStyle=1;align=center;verticalAlign=middle;",
            x,
            HEADER_Y,
            PARTICIPANT_W,
            PARTICIPANT_H,
        )

    # compute total height needed
    total_steps = max(len(messages) + sum(1 for n in notes if n) + 2, 5)
    lifeline_bottom = LIFELINE_START_Y + total_steps * MSG_STEP + 40

    # lifeline lines
    for pid, _, _ in participants:
        x = px[pid]
        line = ET.SubElement(
            root,
            "mxCell",
            {
                "id": f"l_{pid}",
                "value": "",
                "style": "endArrow=none;dashed=1;strokeColor=#888888;strokeWidth=1;",
                "edge": "1",
                "parent": "1",
            },
        )
        g = ET.SubElement(line, "mxGeometry", {"relative": "1", "as": "geometry"})
        ET.SubElement(g, "mxPoint", {"x": str(x), "y": str(LIFELINE_START_Y), "as": "sourcePoint"})
        ET.SubElement(g, "mxPoint", {"x": str(x), "y": str(lifeline_bottom), "as": "targetPoint"})

    # messages and notes interleaved by step index
    # Items: list of (kind, payload)
    items = []
    for m in messages:
        items.append(("msg", m))
    # notes are inserted at their declared y_step_idx; we'll splice
    items_with_notes = []
    note_iter = iter(sorted(notes, key=lambda n: n[0]))
    next_note = next(note_iter, None)
    for idx, m in enumerate(messages):
        while next_note is not None and next_note[0] == idx:
            items_with_notes.append(("note", next_note))
            next_note = next(note_iter, None)
        items_with_notes.append(("msg", m))
    while next_note is not None:
        items_with_notes.append(("note", next_note))
        next_note = next(note_iter, None)

    y = LIFELINE_START_Y + MSG_STEP
    for eid, (kind, payload) in enumerate(items_with_notes, start=1):
        if kind == "msg":
            f_idx, t_idx, label, mkind = payload
            from_pid = participants[f_idx][0]
            to_pid = participants[t_idx][0]
            x_from = px[from_pid]
            x_to = px[to_pid]
            if mkind == "self":
                # self-message loop
                style = (
                    "html=1;endArrow=block;startSize=8;endSize=8;"
                    "exitX=0.5;exitY=0;entryX=0.5;entryY=0;"
                    "rounded=0;curved=0;edgeStyle=orthogonalEdgeStyle;"
                    "strokeColor=#333333;fontSize=11;"
                )
                e = ET.SubElement(
                    root,
                    "mxCell",
                    {
                        "id": f"m_{eid}",
                        "value": label,
                        "style": style,
                        "edge": "1",
                        "parent": "1",
                    },
                )
                g = ET.SubElement(e, "mxGeometry", {"relative": "1", "as": "geometry"})
                ET.SubElement(
                    g, "mxPoint", {"x": str(x_from - 5), "y": str(y), "as": "sourcePoint"}
                )
                ET.SubElement(
                    g,
                    "mxPoint",
                    {"x": str(x_from - 5), "y": str(y + MSG_STEP - 10), "as": "targetPoint"},
                )
                pts = ET.SubElement(g, "Array", {"as": "points"})
                ET.SubElement(pts, "mxPoint", {"x": str(x_from + 50), "y": str(y - 4)})
                ET.SubElement(pts, "mxPoint", {"x": str(x_from + 50), "y": str(y + MSG_STEP - 14)})
                y += MSG_STEP + 4
            else:
                dashed = "1" if mkind == "return" else "0"
                arrow = "open" if mkind == "return" else "block"
                style = (
                    f"endArrow={arrow};html=1;dashed={dashed};strokeColor=#333333;"
                    "fontSize=11;rounded=0;"
                )
                e = ET.SubElement(
                    root,
                    "mxCell",
                    {
                        "id": f"m_{eid}",
                        "value": label,
                        "style": style,
                        "edge": "1",
                        "parent": "1",
                    },
                )
                g = ET.SubElement(e, "mxGeometry", {"relative": "1", "as": "geometry"})
                ET.SubElement(g, "mxPoint", {"x": str(x_from), "y": str(y), "as": "sourcePoint"})
                ET.SubElement(g, "mxPoint", {"x": str(x_to), "y": str(y), "as": "targetPoint"})
                y += MSG_STEP
        else:
            _, span_idxs, text = payload
            xs = [px[participants[i][0]] for i in span_idxs]
            x_left = min(xs) - 60
            x_right = max(xs) + 60
            _cell(
                root,
                f"n_{eid}",
                text,
                "shape=note;whiteSpace=wrap;html=1;backgroundOutline=1;"
                "darkOpacity=0.05;fillColor=#FFF2CC;strokeColor=#D6B656;"
                "fontSize=10;align=center;verticalAlign=middle;",
                x_left,
                y - 4,
                x_right - x_left,
                NOTE_H,
            )
            y += NOTE_H + 6

    return mx


# --- diagram 1: discovery loop -----------------------------------------

DISCOVERY_PARTICIPANTS = [
    ("cron", "Cron 06h UTC", "#D5E8D4"),
    ("ghaw", "gh-aw runtime", "#DAE8FC"),
    ("mem", "Memory branch", "#F8CECC"),
    ("agent", "chaos-monkey agent", "#FFE6CC"),
    ("apm", "apm CLI", "#E1D5E7"),
    ("fixt", "tests/chaos", "#FFF2CC"),
    ("safe", "SafeOutputs", "#DAE8FC"),
    ("maint", "Maintainer", "#D5E8D4"),
    ("main", "main branch", "#F5F5F5"),
]
# index map: 0 cron, 1 ghaw, 2 mem, 3 agent, 4 apm, 5 fixt, 6 safe, 7 maint, 8 main
DISCOVERY_MESSAGES = [
    (0, 1, "trigger schedule", "sync"),
    (1, 3, "spawn container, load persona and skill", "sync"),
    (3, 2, "read findings.md", "sync"),
    (2, 3, "hardened vector signatures", "return"),
    (3, 3, "pick lowest-hardened surface", "self"),
    (3, 5, "call apm_project and bogus_pat_env", "sync"),
    (5, 3, "scratch path + env overrides", "return"),
    (3, 4, "run_apm with args, cwd, env, timeout", "sync"),
    (4, 3, "ChaosResult tuple", "return"),
    (3, 3, "classify graceful / silent / uncontrolled", "self"),
    (3, 5, "write tests/chaos/test_surface_vector.py", "sync"),
    (3, 3, "ruff check + format + pytest -m chaos", "self"),
    (3, 2, "append finding to findings.md", "sync"),
    (3, 6, "emit one Issue + one draft PR", "sync"),
    (6, 7, "GitHub Issue + draft PR", "sync"),
    (1, 2, "push memory branch", "sync"),
    (7, 8, "review and merge draft PR", "sync"),
]
DISCOVERY_NOTES = [
    (1, [1], "Also slash command or workflow_dispatch"),
    (5, [3, 5], "Lazy-load only chosen surface reference"),
    (12, [3], "Validation gate; no SafeOutputs on failure"),
    (17, [8], "Trap file persisted forever on main"),
]

# --- diagram 2: regression-guard loop ----------------------------------

REGRESSION_PARTICIPANTS = [
    ("dev", "Contributor", "#D5E8D4"),
    ("pr", "Pull Request", "#DAE8FC"),
    ("filt", "Path filter", "#FFE6CC"),
    ("ci", "chaos-regression CI", "#DAE8FC"),
    ("chaos", "tests/chaos suite", "#FFF2CC"),
    ("cron2", "Nightly cron 04h UTC", "#D5E8D4"),
    ("main", "main branch", "#F5F5F5"),
    ("maint", "Maintainer", "#D5E8D4"),
]
# 0 dev, 1 pr, 2 filt, 3 ci, 4 chaos, 5 cron2, 6 main, 7 maint
REGRESSION_MESSAGES = [
    (0, 1, "open or push commit", "sync"),
    (1, 2, "announce changed paths", "sync"),
    (2, 3, "trigger workflow (if src/ matched)", "sync"),
    (3, 4, "pytest -m chaos -n auto", "sync"),
    (4, 3, "pass or fail per trap", "return"),
    (3, 1, "required check passes (green)", "return"),
    (3, 1, "required check fails (red)", "return"),
    (1, 0, "investigate, fix regression or flip xfail", "return"),
    (5, 3, "scheduled trigger on main 04h UTC", "sync"),
    (3, 4, "pytest -m chaos -n auto", "sync"),
    (4, 3, "pass or fail", "return"),
    (3, 7, "notify on regression (failure alert)", "sync"),
    (7, 6, "bisect 24h window; revert or fix PR", "sync"),
]
REGRESSION_NOTES = [
    (3, [2, 3], "Filter on src/apm_cli/**, tests/chaos/**, pyproject.toml, apm.yml/lock"),
    (9, [5, 3], "Scheduled BEFORE chaos-monkey 06h UTC to disambiguate signals"),
]

# --- diagram 3: composition --------------------------------------------


def _build_composition():
    mx = ET.Element(
        "mxGraphModel",
        {
            "dx": "1422",
            "dy": "800",
            "grid": "1",
            "gridSize": "10",
            "guides": "1",
            "tooltips": "1",
            "connect": "1",
            "arrows": "1",
            "fold": "1",
            "page": "1",
            "pageScale": "1",
            "pageWidth": "1400",
            "pageHeight": "900",
            "math": "0",
            "shadow": "0",
        },
    )
    root = ET.SubElement(mx, "root")
    ET.SubElement(root, "mxCell", {"id": "0"})
    ET.SubElement(root, "mxCell", {"id": "1", "parent": "0"})

    _cell(
        root,
        "title",
        "<b>Composition: how the discovery and regression loops connect</b>",
        "text;html=1;align=center;verticalAlign=middle;fontSize=18;fontStyle=1;",
        80,
        20,
        1240,
        36,
    )

    # left swimlane: discovery loop
    _cell(
        root,
        "lane_disc",
        "Discovery loop (daily, gh-aw runtime)",
        "rounded=0;whiteSpace=wrap;html=1;fillColor=#FFE6CC;strokeColor=#D79B00;"
        "fontSize=13;fontStyle=1;verticalAlign=top;align=center;dashed=1;",
        80,
        100,
        540,
        700,
    )
    # right swimlane: regression loop
    _cell(
        root,
        "lane_reg",
        "Regression-guard loop (per-PR + nightly CI)",
        "rounded=0;whiteSpace=wrap;html=1;fillColor=#DAE8FC;strokeColor=#6C8EBF;"
        "fontSize=13;fontStyle=1;verticalAlign=top;align=center;dashed=1;",
        780,
        100,
        540,
        700,
    )

    # discovery nodes
    _cell(
        root,
        "n_agent",
        "chaos-monkey agent\n(persona + skill)",
        "rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#D79B00;fontSize=12;",
        150,
        160,
        200,
        60,
    )
    _cell(
        root,
        "n_run",
        "run_apm\n(subprocess + sanitised env)",
        "rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#D79B00;fontSize=12;",
        150,
        260,
        200,
        60,
    )
    _cell(
        root,
        "n_classify",
        "Classify outcome\ngraceful / silent / uncontrolled",
        "rhombus;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#D79B00;fontSize=11;",
        150,
        360,
        200,
        70,
    )
    _cell(
        root,
        "n_writetrap",
        "Write trap file\ntests/chaos/test_*.py",
        "rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#D79B00;fontSize=12;",
        150,
        470,
        200,
        60,
    )
    _cell(
        root,
        "n_safe",
        "SafeOutputs\n(1 Issue + 1 draft PR)",
        "rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#D79B00;fontSize=12;",
        150,
        570,
        200,
        60,
    )
    _cell(
        root,
        "n_mem",
        "Memory branch\nfindings.md\n(dedup signatures)",
        "shape=cylinder3;whiteSpace=wrap;html=1;boundedLbl=1;backgroundOutline=1;size=15;"
        "fillColor=#FFFFFF;strokeColor=#D79B00;fontSize=11;",
        400,
        260,
        180,
        80,
    )

    # central persistent state
    _cell(
        root,
        "n_main",
        "main branch\ntests/chaos/*.py\n(persistent traps)",
        "shape=cylinder3;whiteSpace=wrap;html=1;boundedLbl=1;backgroundOutline=1;size=15;"
        "fillColor=#F5F5F5;strokeColor=#333333;fontSize=12;fontStyle=1;",
        620,
        420,
        160,
        90,
    )

    # regression nodes
    _cell(
        root,
        "n_prtrigger",
        "PR opens\n(path-filtered)",
        "rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#6C8EBF;fontSize=12;",
        830,
        160,
        200,
        60,
    )
    _cell(
        root,
        "n_cronregress",
        "Nightly cron 04h UTC\non main",
        "rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#6C8EBF;fontSize=12;",
        1080,
        160,
        200,
        60,
    )
    _cell(
        root,
        "n_runci",
        "pytest -m chaos -n auto\n(chaos-regression workflow)",
        "rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#6C8EBF;fontSize=12;",
        960,
        290,
        220,
        70,
    )
    _cell(
        root,
        "n_verdict",
        "Green: merge\nRed: regression caught",
        "rhombus;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#6C8EBF;fontSize=11;",
        960,
        410,
        220,
        70,
    )
    _cell(
        root,
        "n_fix",
        "Fix PR\nor xfail flip\nor revert",
        "rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#6C8EBF;fontSize=12;",
        960,
        530,
        220,
        60,
    )

    # metric box (loop convergence)
    _cell(
        root,
        "n_metric",
        "chaos_metric.py\nhardened_findings count\n(autoloop signal)",
        "rounded=1;whiteSpace=wrap;html=1;fillColor=#E1D5E7;strokeColor=#9673A6;fontSize=11;",
        550,
        620,
        200,
        70,
    )

    # discovery edges
    edges = [
        ("e1", "n_agent", "n_run", "invoke"),
        ("e2", "n_run", "n_classify", "ChaosResult"),
        ("e3", "n_classify", "n_writetrap", "evidence"),
        ("e4", "n_writetrap", "n_safe", "PR intent"),
        ("e5", "n_agent", "n_mem", "read"),
        ("e6", "n_mem", "n_agent", "signatures"),
        ("e7", "n_writetrap", "n_mem", "append"),
        ("e8", "n_safe", "n_main", "human-merged PR"),
        ("e9", "n_main", "n_runci", "checked out"),
        ("e10", "n_prtrigger", "n_runci", "trigger"),
        ("e11", "n_cronregress", "n_runci", "trigger"),
        ("e12", "n_runci", "n_verdict", "result"),
        ("e13", "n_verdict", "n_fix", "if red"),
        ("e14", "n_fix", "n_main", "merged fix"),
        ("e15", "n_main", "n_metric", "count traps"),
        ("e16", "n_metric", "n_agent", "convergence signal"),
    ]
    for eid, src, tgt, lbl in edges:
        e = ET.SubElement(
            root,
            "mxCell",
            {
                "id": eid,
                "value": lbl,
                "style": "endArrow=block;html=1;rounded=0;strokeColor=#333333;fontSize=10;edgeStyle=orthogonalEdgeStyle;",
                "edge": "1",
                "parent": "1",
                "source": src,
                "target": tgt,
            },
        )
        ET.SubElement(e, "mxGeometry", {"relative": "1", "as": "geometry"})

    # legend
    _cell(
        root,
        "legend",
        "<b>Legend</b><br/>Orange = discovery (daily gh-aw)<br/>Blue = regression-guard (CI)<br/>Grey cylinder = persistent state on main<br/>Purple = autoloop metric",
        "rounded=0;whiteSpace=wrap;html=1;fillColor=#FAFAFA;strokeColor=#333333;"
        "fontSize=10;align=left;verticalAlign=top;",
        80,
        820,
        380,
        60,
    )

    return mx


# --- assemble multi-page drawio ----------------------------------------


def _serialise(mxgraph):
    """Return mxGraphModel as a compact XML string."""
    rough = ET.tostring(mxgraph, encoding="unicode")
    return rough


def _build_drawio():
    """Wrap pages in the <mxfile> container."""
    mxfile = ET.Element(
        "mxfile",
        {
            "host": "Electron",
            "modified": "2026-05-13T16:42:00.000Z",
            "agent": "chaos-monkey-gen",
            "etag": "chaos-monkey",
            "version": "24.0.0",
            "type": "device",
        },
    )

    pages = [
        (
            "Discovery loop",
            _build_page(
                "Chaos-monkey discovery loop (daily)",
                DISCOVERY_PARTICIPANTS,
                DISCOVERY_MESSAGES,
                DISCOVERY_NOTES,
            ),
        ),
        (
            "Regression guard",
            _build_page(
                "Chaos-regression CI (per-PR + nightly)",
                REGRESSION_PARTICIPANTS,
                REGRESSION_MESSAGES,
                REGRESSION_NOTES,
            ),
        ),
        ("Composition", _build_composition()),
    ]

    for i, (name, mx) in enumerate(pages, start=1):
        diagram = ET.SubElement(mxfile, "diagram", {"id": f"page-{i}", "name": name})
        diagram.append(mx)

    rough = ET.tostring(mxfile, encoding="utf-8", xml_declaration=True)
    # Pretty-print for human-editability; input is locally-generated and trusted.
    pretty = minidom.parseString(rough).toprettyxml(indent="  ", encoding="utf-8")  # noqa: S318
    return pretty


def main():
    out = Path("docs/diagrams/chaos-monkey.drawio")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(_build_drawio())
    print(f"[+] wrote {out} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
