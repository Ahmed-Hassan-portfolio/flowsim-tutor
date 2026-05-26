# WellEditorHelp

Reference for the Well Editor sub-tool in FlowSim. Invented content for the FlowSim Tutor RAG demo.

## Table of Contents

- Overview
- Well structure
  - Tubing flowpath
  - Annulus flowpath
- Equipment
  - Valve
    - Model description
    - How to use
  - Packer
    - Model description
    - How to use
- Boundary conditions
- Coordinate conventions

---

## Overview

The Well Editor builds a multi-flowpath well model from a deviation survey and a list of completion equipment. It produces one or more `BRANCH` blocks (one per flowpath) plus the necessary `NODE` and equipment definitions.

A well typically has two flowpaths: the **tubing** (where the produced or injected fluid moves) and the **annulus** (the space between tubing and casing). The annulus is often closed at both ends but contributes to heat exchange and pressure communication.

---

## Well structure

### Tubing flowpath

The tubing is a single continuous pipe from the wellhead to the bottom-hole. It is broken into sections at every change of diameter, material, or downhole component. The Well Editor places `NODE` instances at the wellhead (`TH`), at the tubing-reservoir junction (`BH`), and at any intermediate component boundaries.

### Annulus flowpath

The annulus runs from the casing head (`CH`) at the top to the packer at the bottom. By default the annulus is closed at the top (`CLOSED` node) and terminated by an `INTERNAL` node at the packer.

When studying behavior that does not depend on annulus dynamics (e.g. a barrier test of the downhole valve only), it is acceptable to disable the annulus flowpath in the Well Editor; this simplifies the model and enables the steady-state preprocessor.

---

## Equipment

### Valve

#### Model description

A valve is a section-boundary element that imposes a configurable choke or full closure between two pipe sections. The valve area follows a time schedule defined by `(TIME, SIZE)` pairs; `SIZE = 0` means fully closed and `SIZE = 1` means fully open.

#### How to use

1. Right-click the tubing flowpath at the desired depth and choose `Insert > Valve`.
2. Set the `LABEL` (e.g. `DHSV` for a downhole safety valve).
3. In the property editor, enter the schedule. For example:
   1. `TIME = 0, 600, 601, 3600` (seconds)
   2. `SIZE = 1, 1, 0, 0`
4. Confirm the valve location matches the intended `ABSPOSITION` (pipeline length from the branch inlet).
5. Apply. The valve is now part of the case.

If the `OPENING` property is grayed out, you are editing a fixed-area choke; the `SIZE` time-schedule is the supported way to model an opening or closing valve.

### Packer

#### Model description

A packer is a section-boundary element that closes the annulus at a chosen depth. It has no time schedule (a packer is either present or not). The packer is treated as a thermal barrier with a small heat-transfer coefficient.

#### How to use

1. Right-click the annulus flowpath at the desired depth and choose `Insert > Packer`.
2. Confirm the depth; a packer typically sits just above the production zone.
3. Apply.

A packer cannot be inserted in the tubing flowpath. To create a barrier in tubing, use a valve with `SIZE = 0` for the entire simulation.

---

## Boundary conditions

The four boundary conditions a well case must specify are:

1. **Wellhead (TH)** -- typically `PRESSURE` (production) or `MASSFLOW` (injection).
2. **Bottom-hole (BH)** -- typically `PRESSURE` (reservoir-driven) or `INTERNAL` if connected to a reservoir model.
3. **Casing head (CH)** -- usually `CLOSED`.
4. **Tubing-annulus junction (TI)** -- usually `INTERNAL`.

For a controlled injection case where the injection rate is the independent variable, set `TH` to `MASSFLOW` with a negative value (sign convention: positive flow points from branch inlet to outlet; injection from the wellhead is negative because the well's tubing inlet is at the bottom-hole).

---

## Coordinate conventions

The Well Editor sets the **inlet** of the tubing flowpath at the **bottom-hole**, not the wellhead. This means:

- Pipeline length 0 = bottom-hole.
- Pipeline length 1700 m = wellhead, for a well with 1700 m of tubing length.
- `ABSPOSITION` on `TRENDDATA` and `PROFILEDATA` refers to pipeline length, not depth.

To convert measured depth (MD, where MD = 0 at the wellhead and MD = total at the bottom) to `ABSPOSITION`, use:

```
ABSPOSITION = total_tubing_length - (MD - MD_inlet)
```

For a vertical well with MD = 100 m at the wellhead and MD = 1800 m at the bottom-hole, the tubing inlet is at MD = 1800 m, total length = 1700 m, and the wellhead is at `ABSPOSITION = 1700`.

Always verify the inlet/outlet mapping in `Network Connections Overview` immediately after generating the well, or the schedule for the downhole valve may end up at the wrong location.
