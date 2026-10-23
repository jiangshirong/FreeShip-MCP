# Changes to the pinned upstream / 上游改动

Base: FreeShip Plus `1de17e99fb2b1cc559cdf27c5cafb595a627a641`.
The vendored subset includes all source required by this headless build, original forms
needed to compile shared units, resources and license notices. Unused upstream sample
ships, manuals, installers and precompiled programs are omitted.

| File | Change |
|---|---|
| `Units/FreeShip.inc` | `FREESHIP_HEADLESS` guards form construction, async GUI rebuild scheduling and load cursors. Invalid signature/version raises an exception. Preview is cloned from stored JPEG data. Headless preview ownership is released on destruction. Reject future file formats above `CurrentVersion`. |
| `Units/FreeShipUnit.pas` | Headless cached-preview field; geometry/hydrostatic interfaces unchanged. |
| `Units/FreeLogger.pas` | No exception dialog is constructed in headless initialization. |
| `Units/FreeProjectSettings.inc` | Retain loaded preview for headless save; no screenshot generation. |
| `Units/FreeFileBuffer.pas` | Preserve stored JPEG dimensions and binary record alignment bytes; reject truncated records before copying. Numeric field readers/writers remain upstream. |
| `.gitignore` | Keep the upstream cursor resource required for a clean compile. |

`engine/HeadlessLackenby.pas` contains the extracted upstream Simpson and point-transform
methods. UI controls are replaced by typed parameters, selected-layer arrays, status fields
and exceptions. Undo/UI redraw are unnecessary in the isolated disposable process. Locked
points require an explicit opt-in. Original stopping rules and 15-iteration default remain.

`engine/HeadlessModel.pas` uses native model buffers, scaling, intersections and hydrostatics.
The explicit section API retains requested empty endpoints instead of the GUI helper's
discard-empty behavior. It invokes only hydrostatic calculation flags that do not write GUI
SAC/Bonjean report files. It does not alter hydrostatic or surface mathematics.

`Units/FreeHydrostaticCalc.inc`, `FreeIntersection.inc`, `FreeSubdivisionSurface.inc`,
`FreeSpline.inc` and the rest of the geometry method bodies remain unchanged from upstream.
DXF curve sampling follows `FreeLinesplanFrme.AddSpline`; the portable writer arranges the
three projections and serializes with ezdxf. XLSX/CSV writers consume native numeric results.

## Adapter additions in 0.3.0

`engine/HeadlessEditing.pas` calls the original subdivision point/edge/face methods.
It adds selection, lock protection and result reporting; it does not replace the
subdivision mathematics. `HeadlessModel.pas` exposes full control-net tables, sampled
native knuckles, selected-layer subdivided boundaries/creases and view silhouettes.
Preview section changes are in memory only. `quality.py` computes documented discrete
sample diagnostics, not a replacement native hydrostatic or fairing solver.
