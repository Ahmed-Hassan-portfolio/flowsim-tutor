# FlowSimSampleCasesHelp

Sample cases shipped with FlowSim. All examples are invented for the FlowSim Tutor RAG demo.

## Table of Contents

- Overview
- Sample case index
- Pipeline cases
  - 01_simple_pipeline
    - Model description
    - How to use
  - 02_riser_slugging
    - Model description
    - How to use
- Well cases
  - 03_vertical_injection
    - Model description
    - How to use
  - 04_horizontal_producer
- Process cases
  - 05_shutdown_response

---

## Overview

The sample case library is a set of small, fully self-contained `.fsi` files that demonstrate one feature at a time. Each case has a short description, a recommended PVT file, and a checklist of what to look for in the results. They are intended as a starting point for new users and as regression tests for the simulator.

---

## Sample case index

| ID | Title | Domain | Run time |
|----|-------|--------|----------|
| 01 | Simple pipeline | Pipeline | < 1 min |
| 02 | Riser slugging | Pipeline | 5-10 min |
| 03 | Vertical injection well | Well | 2-3 min |
| 04 | Horizontal producer | Well | 5-8 min |
| 05 | Shutdown response | Process | 1-2 min |

---

## Pipeline cases

### 01_simple_pipeline

#### Model description

A single 1000 m horizontal pipeline with a gas-oil mixture flowing at a fixed inlet mass flow. The outlet is at fixed pressure. This case demonstrates the minimum keyword set required to run FlowSim and produces a clean steady-state in fewer than 50 time steps.

#### How to use

1. Open `samples/01_simple_pipeline/case.fsi` in the GUI or in a text editor.
2. Verify the `FILES > PVTFILE` reference resolves; the default points to `pvt/light_gas_oil.tab`.
3. Run the case. Total wall time should be under one minute.
4. Open the trend plot for `PT` at the outlet. The pressure should approach the boundary condition value within the first 5 seconds.
5. Open the profile plot at `t = ENDTIME`. The pressure gradient should be smooth and monotonic.

If the pressure plot shows oscillations, lower `MAXDT` in the `INTEGRATION` block by a factor of two.

### 02_riser_slugging

#### Model description

A pipeline-riser geometry with a low gas-liquid ratio designed to produce terrain-induced slugging in the vertical riser. The case has a 2 km pipeline at -2 degrees inclination followed by a 200 m vertical riser. The expected behavior is a quasi-periodic slug cycle with a period of about 90 s.

#### How to use

1. Open `samples/02_riser_slugging/case.fsi`.
2. Run with `ENDTIME = 7200` (two hours) to capture several slug cycles.
3. Plot `GT` (mass flow) at the riser top as a trend. You should see clear cycles.
4. Plot `HOL` (liquid holdup) profile at the moment of maximum riser-top flow. The slug body should occupy the upper half of the riser.

To suppress the slugging for diagnostic purposes, raise the inlet `MASSFLOW` by 50%. The system should transition to stratified flow within ten minutes.

---

## Well cases

### 03_vertical_injection

#### Model description

A vertical injection well, 1900 m deep, with a constant mass flow boundary at the wellhead and a pressure boundary at the bottom-hole. The case demonstrates a controlled injection followed by a step-change shut-in at t = 600 s. The expected behavior is a rapid pressure spike at the wellhead followed by hydrostatic equilibration.

#### How to use

1. Open `samples/03_vertical_injection/case.fsi`.
2. Confirm the `NODE` at the wellhead has `TYPE = MASSFLOW` with a time-varying schedule.
3. Run the case. Wall time is 2-3 minutes.
4. Plot `PT` trend at the wellhead. The shut-in spike should be visible at t = 600 s.
5. Plot `PT` profile at t = 3600 s. The gradient should match hydrostatic equilibrium against the bottom-hole pressure boundary.

### 04_horizontal_producer

A 2 km horizontal section connected to a 1.8 km vertical riser, producing at a fixed wellhead pressure. The case demonstrates flow-from-reservoir behavior and is the basis for the artificial-lift sample in the documentation appendix.

---

## Process cases

### 05_shutdown_response

A surface separator connected to a 500 m export line. The case starts in steady-state with a constant outlet pressure, then closes the outlet valve at t = 120 s. The expected behavior is a pressure ramp-up against the closed valve until the line reaches the bubble point of the contained fluid.

To use:

1. Open `samples/05_shutdown_response/case.fsi`.
2. Run with `ENDTIME = 600`.
3. Plot `PT` trend at the valve. The ramp should approach the closed-end pressure asymptotically.
4. Compare against the analytical estimate `P_final = P_initial + rho * g * L * sin(alpha)` for the static head contribution.
