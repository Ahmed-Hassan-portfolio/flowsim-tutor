# ProfileGeneratorHelp

Reference for the Profile Generator sub-tool in FlowSim. Invented content for the FlowSim Tutor RAG demo.

## Table of Contents

- Overview
- Modes
  - Manual mode
  - Survey-driven mode
  - Parametric mode
- Wall and insulation profiles
  - Defining a wall
    - Model description
    - How to use
  - Defining an insulation
    - Model description
    - How to use
- Output

---

## Overview

The Profile Generator builds an elevation profile and a wall/insulation profile that the rest of FlowSim consumes. It produces either an inline data block embedded in the `.fsi` file or a separate `.profile` file referenced from `FILES`.

The Profile Generator is invoked from the Pipeline Editor or directly from the project tree under `Geometry > Profile`.

---

## Modes

### Manual mode

In manual mode the user enters elevation control points in a table. Between control points the profile is linear. This mode is best for short, well-known geometries (e.g. a single riser).

### Survey-driven mode

In survey-driven mode the elevation is read from the Z column of an imported survey. Inclination is computed from neighboring control points and snapped to the nearest 0.1 degrees.

### Parametric mode

In parametric mode the profile is defined by a formula: an inclination versus arc length curve. Built-in profiles include `STRAIGHT`, `SAG`, `CATENARY`, and `STEPPED`. Use parametric mode for synthetic studies and unit tests.

---

## Wall and insulation profiles

### Defining a wall

#### Model description

A wall is a layered structure of one or more materials between the pipe interior and the environment. Each layer has a thickness and a material reference. The thermal resistance and heat capacity are computed from the layer stack.

#### How to use

1. Open `Materials > Wall Library`.
2. Click `New wall` and give it a label (e.g. `carbon_steel_10mm`).
3. Add one layer per material: `Add layer > steel_carbon`, thickness 0.010 m.
4. Repeat for additional layers (typically a corrosion-resistant cladding or external coating).
5. Click `Apply`. The new wall is now selectable in the pipe table.

A wall must have at least one layer with a non-zero thickness. The editor refuses to save a wall with zero total thickness.

### Defining an insulation

#### Model description

Insulation is a separate layered structure applied around the wall. It is distinct from the wall because it is often replaceable (e.g. removable insulation jackets) and because the conductivity is typically much lower.

#### How to use

1. Open `Materials > Insulation Library`.
2. Click `New insulation` and give it a label.
3. Add layers in order from the wall outward.
4. Set `IS_REMOVABLE = TRUE` if the insulation can be removed during inspection; the simulator will issue a warning if the temperature exceeds the insulation's rated maximum.

---

## Output

The Profile Generator writes its result back to the `PIPELINE` block in one of two ways:

1. **Inline**: the elevation and wall references are written as part of the `LINE` rows in the pipe table.
2. **External**: the editor writes a `.profile` file with the geometry, and the `PIPELINE` block adds a `PROFILE = my_pipeline.profile` key referencing it.

External profiles are recommended when the same geometry is shared across multiple cases. Inline profiles are recommended when the case is fully self-contained.
