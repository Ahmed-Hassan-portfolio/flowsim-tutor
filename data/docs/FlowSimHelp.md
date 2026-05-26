# FlowSimHelp

Reference manual for the FlowSim flow-simulation toolkit. All content in this corpus is invented and provided as a synthetic example for the FlowSim Tutor RAG pipeline.

## Table of Contents

- Introduction
- Background
- Applications
- Input files
- Modeling basics
  - Transport equations
  - Flow regimes
  - Pipe system modeling
    - LINE
    - Single Phase
  - Numerics
    - Time step control
    - Steady-state preprocessor
      - Model description
      - How to use
    - Restart
      - Model description
      - How to use
  - Tuning
    - Model description
    - How to use
- Fluids and PVT
  - PVT lookup tables
  - Compositional tracking
- Keywords
  - CASE
  - OPTIONS
  - INTEGRATION

---

## Introduction

FlowSim is a transient multiphase flow simulator for pipelines and wells. It solves mass, momentum, and energy equations on a one-dimensional grid using a pressure-correction scheme. Each section of this manual is structured so that a "Model description" explains the physics, and a "How to use" gives the practical input.

---

## Background

The development of FlowSim began with the need for fast, accurate transient simulations of multiphase pipelines. It is now used across upstream, midstream, and process design workflows. The simulator supports compositional and black-oil tracking, with a pluggable PVT interface.

---

## Applications

Common application areas include:

1. Pipeline transient analysis during start-up, shut-in, and pigging operations.
2. Flow assurance studies for slugging, wax deposition, and hydrate management.
3. Well integrity testing including downhole barrier evaluation.
4. Compressor and pump shutdown response.

For each application class, FlowSim provides a sample case in the SampleCases folder, documented in `FlowSimSampleCasesHelp.md`.

---

## Input files

A FlowSim case consists of a single `.fsi` input file plus any referenced PVT, geometry, and trend files. The `.fsi` file is a keyword-structured text file. The minimum elements are:

1. A `CASE` block with project metadata.
2. A `FILES` block referencing PVT tables.
3. One or more `PIPELINE` or `BRANCH` blocks defining geometry.
4. `NODE` blocks for boundary conditions.
5. An `OPTIONS` block selecting the solver and physical models.
6. An `INTEGRATION` block defining the time-stepping range.

Each block is terminated by a semicolon. Comments start with `!` and continue to end of line.

---

## Modeling basics

This chapter covers the physical models and numerical schemes that FlowSim implements.

---

### Transport equations

FlowSim solves the volume-averaged conservation laws for each phase: gas, oil, and water. The momentum equations are coupled through interfacial friction closures. The energy equation is solved per mixture, with heat exchange to the wall and external environment.

---

### Flow regimes

Five primary flow regimes are recognized: stratified, slug, annular, bubble, and dispersed-bubble. The regime map is selected automatically based on local conditions, but can be overridden in the `OPTIONS` block via `FLOWREGIME = USER` for diagnostic runs.

---

### Pipe system modeling

Pipe system geometry is built from `LINE` and `BRANCH` elements. A `LINE` is a single pipe section with constant diameter, roughness, and wall properties. A `BRANCH` is a sequence of one or more `LINE` elements with shared boundary conditions at the inlet and outlet `NODE`.

---

#### LINE

The `LINE` keyword defines one segment of pipe. Required arguments:

- `DIAMETER` (inner diameter, m)
- `ROUGHNESS` (absolute roughness, m)
- `WALL` (label of a `WALL` material)
- `LENGTH` (segment length, m)

Optional arguments include `INCLINATION` (degrees from horizontal), `BURIALDEPTH` (m), and `INSULATION` (label).

---

#### Single Phase

Single-phase analysis can be enabled per pipe with `FLOWMODEL = SINGLEPHASE`. In this mode the closure relations for slip and entrainment are bypassed, which gives a significant speed-up for liquid-only or gas-only segments.

---

### Numerics

The Numerics group collects keywords that control the time-stepping and convergence behavior.

---

#### Time step control

FlowSim uses adaptive time-stepping. The `MAXDT` and `MINDT` keys in the `INTEGRATION` block bound the step size; the actual size is chosen to keep the Courant number below `MAXCFL` (default 0.9). For stiff transients, lowering `MAXDT` to 0.1 s typically prevents oscillations at the cost of a longer run.

---

#### Steady-state preprocessor

The steady-state preprocessor produces a consistent initial condition by solving the time-independent form of the conservation equations.

---

##### Model description

The steady-state preprocessor solves the time-independent form of the conservation equations to produce a consistent initial condition. It uses a damped Newton iteration that converges in 5-15 iterations for well-posed problems.

---

##### How to use

1. In the `OPTIONS` block, set `STEADYSTATE = ON`.
2. Provide initial guesses for pressure at every `NODE` with `INITIALPRESSURE`.
3. Run the case. The preprocessor writes a `.ic` file containing the converged steady-state.
4. For subsequent runs that need the same initial condition, set `STEADYSTATE = OFF` and reference the `.ic` file in `FILES`.

If the preprocessor fails to converge, check that the boundary conditions are physically consistent (e.g. inlet `MASSFLOW` is matched by outlet `PRESSURE` at a reasonable level).

---

#### Restart

Restart files store the full simulator state at a chosen time. Loading a restart skips the steady-state phase and resumes integration from the stored state.

---

##### Model description

Restart files store the full simulator state at a chosen time: pressures, temperatures, holdups, mass flows, and any tracked compositional fractions. Loading a restart bypasses the steady-state preprocessor and resumes integration from the stored state.

---

##### How to use

1. In the source run, add `RESTART_OUT = my_state.rst` to the `OUTPUT` block and `RESTART_TIME = 3600` to write at t = 3600 s.
2. In the new run, add `RESTART_IN = my_state.rst` to the `FILES` block.
3. Adjust `INTEGRATION` so the new `ENDTIME` is past the restart time.

A restart file is portable only between runs that share the same geometry, fluid, and numerical settings.

---

### Tuning

Tuning parameters modify the closure relations to match field or laboratory data.

---

#### Model description

Tuning parameters modify the closure relations to match field or laboratory data. The default closures are conservative; tuning is normally needed only for very high-rate gas-condensate systems or for cases where the holdup is known to be biased.

---

#### How to use

1. Identify the parameter to tune (e.g. `LIQUID_FRICTION_FACTOR`).
2. Add a `TUNING` block: `TUNING LIQUID_FRICTION_FACTOR = 0.9;`
3. Document the tuning in a comment with the data source.
4. Re-run and compare to the measurement.

Avoid tuning more than two parameters at once: the optimum becomes ill-defined.

---

## Fluids and PVT

The Fluids and PVT chapter describes how phase properties are supplied to the simulator.

---

### PVT lookup tables

PVT lookup tables provide phase properties as a function of pressure and temperature (PT tables) or pressure and enthalpy (PH tables). PH tables are recommended for systems with strong Joule-Thomson cooling, since the enthalpy variable remains single-valued across the saturation line.

---

### Compositional tracking

When the composition varies in space or time (e.g. during start-up of a mixed stream), enable compositional tracking with `COMPOSITIONAL = MULTI`. The solver tracks component mass fractions on the grid and re-evaluates PVT at each cell.

---

## Keywords

This chapter is a reference for the most commonly used keyword blocks.

---

### CASE

The `CASE` block contains project metadata: title, author, date, and an optional description. None of these are required for the simulation to run, but they are written to the output files for traceability.

---

### OPTIONS

The `OPTIONS` block selects the physical models and solver mode. Common entries:

1. `FLOWMODEL` -- choose `STANDARD`, `SINGLEPHASE`, or `EXPERIMENTAL`.
2. `COMPOSITIONAL` -- `OFF`, `SINGLE`, or `MULTI`.
3. `SOLVER` -- `STANDARD` or `IMPLICIT`.
4. `STEADYSTATE` -- `ON` to run the preprocessor first.
5. `FLOWREGIME` -- `AUTO` (default) or `USER`.

---

### INTEGRATION

The `INTEGRATION` block bounds the time-stepping. Required keys:

- `STARTTIME` (s)
- `ENDTIME` (s)
- `MAXDT` (s)
- `MINDT` (s)

The optional `DTSTART` key sets the very first attempted step; if omitted, FlowSim uses `MINDT`.
