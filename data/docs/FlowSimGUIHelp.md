# FlowSimGUIHelp

Guide to the FlowSim graphical user interface. Content is invented for the FlowSim Tutor RAG demo.

## Table of Contents

- Introduction
- Workspace layout
  - Project tree
  - Property editor
  - Plot panel
- Common tasks
  - Creating a new case
    - Model description
    - How to use
  - Editing geometry
    - Model description
    - How to use
  - Running a simulation
- Plot configuration
  - Trend plots
  - Profile plots
- Preferences
  - Display units
  - Keyboard shortcuts

---

## Introduction

The FlowSim GUI is a desktop application that wraps the simulation engine. It provides a project tree for organizing cases, a property editor for keyword input, and an integrated plot panel for inspecting results. The GUI saves projects as `.fsp` files; the underlying `.fsi` case files are still plain text and can be edited externally.

---

## Workspace layout

### Project tree

The project tree on the left lists every case in the project. Each case node has children for `Geometry`, `Fluids`, `Boundary conditions`, `Options`, and `Output`. Right-click on any node to add, duplicate, or delete an entry. Drag-and-drop reorders sibling nodes.

### Property editor

When a node is selected in the project tree, its properties appear in the property editor on the right. Properties are grouped by keyword. Required fields are shown in bold; optional fields are dimmed until edited.

### Plot panel

The plot panel at the bottom shows trend or profile data. The top toolbar of the panel toggles between trend (time on the x-axis) and profile (pipeline length on the x-axis). Multiple curves can be overlaid by ctrl-clicking variables in the variable picker.

---

## Common tasks

### Creating a new case

#### Model description

A new case starts from a blank template with the minimum keywords required to run: `CASE`, `OPTIONS`, `INTEGRATION`, one `PIPELINE`, two `NODE`s, and one `BRANCH`. The user fills in fluid, geometry, and boundary conditions.

#### How to use

1. Choose `File > New Case` from the menu (shortcut: Ctrl+N).
2. In the dialog, enter a case name and choose a template (`Single pipe`, `Pipeline + riser`, `Well`).
3. Click `Create`. The project tree updates with the new case.
4. Open `Geometry > PIPELINE_1` and edit the `LENGTH`, `DIAMETER`, and elevation profile.
5. Open `Boundary conditions > NODE_1` and `NODE_2` and set inlet/outlet conditions.
6. Save the project with `File > Save Project` (Ctrl+S).

### Editing geometry

#### Model description

Geometry editing covers the pipe-section table, the elevation profile, the wall material, and the insulation. Each pipe section is one row in a table; the elevation profile is a piecewise-linear curve over the table's `LENGTH` axis.

#### How to use

1. Select the `PIPELINE` node in the project tree.
2. In the property editor, click `Edit pipe table`. A spreadsheet-style table opens.
3. Enter rows for each section: `LENGTH`, `DIAMETER`, `ROUGHNESS`, `WALL`, `INCLINATION`.
4. Click `Apply` to push changes back to the keyword input.
5. Click `Plot profile` to visualize the elevation profile.

To import geometry from a `.csv` file, use `File > Import > Pipe table CSV`.

### Running a simulation

A case can be run from the GUI in two modes:

1. `Interactive` -- the GUI streams progress and trend data as the run proceeds. Useful for monitoring convergence.
2. `Batch` -- the GUI launches the engine in a separate process and shows a console window with detailed error output. Use this when debugging a case that fails to start.

Press F5 to run in the active mode, or F4 to force batch mode.

---

## Plot configuration

### Trend plots

Trend plots show one or more variables versus time at a chosen reporting point. The reporting point is selected by `ABSPOSITION` (pipeline length from the branch inlet) or by `SECTION` (section index, 1-based).

To configure a trend plot:

1. Open the `Output > TRENDDATA` node.
2. Add a row for each variable you want to record (e.g. `PT`, `TM`, `GT`).
3. Set `ABSPOSITION` or `SECTION` to choose the reporting point.
4. Set `DTPLOT` to the desired output interval (s).

### Profile plots

Profile plots show one or more variables versus pipeline length at a chosen time. The reporting times are listed in `PROFILEDATA > TIME`.

By convention, the x-axis is pipeline length from the `BRANCH` inlet. For well models built in the Well Editor, the inlet is at the bottom of the well; the x-axis therefore runs from the reservoir to the wellhead.

---

## Preferences

### Display units

The display units affect only what the GUI shows; the underlying case file is always in SI. Open `Preferences > Units` to choose between SI, field, and metric-engineering unit systems. You can also override individual quantities (e.g. show pressure in `bar` while keeping flow in `kg/s`).

### Keyboard shortcuts

| Shortcut | Action |
|----------|--------|
| Ctrl+N | New case |
| Ctrl+S | Save project |
| Ctrl+O | Open project |
| F3 | Verify case (syntax + reference check) |
| F4 | Run in batch mode |
| F5 | Run in active mode |
| F6 | Stop running simulation |
| Ctrl+L | Focus plot variable picker |
