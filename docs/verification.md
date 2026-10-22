# Verification / 验证

Run `python -m pytest -q` after building the engine and generating the synthetic examples.
The tests use compiled Pascal calculations, not a Python replacement solver.

- Analytic half-box mirrored about y=0: volume, centre of buoyancy, waterplane area,
  transverse and longitudinal BM, adjacent normals and topology.
- Uniform scaling: volume ×s³, waterplane area ×s², BM ×s; mesh and layers reload.
- Separate geometric/corrected volume and metric/imperial physical unit checks.
- Native FBM byte-identity; native FBM/FTM conversions for fv335 and fv462.
- Synthetic Lackenby transform with original convergence thresholds; independent 3D
  hydrostatic residuals and saved-model reload check.
- Dry hull, malformed file, infeasible target, timeout and cancellation produce no
  falsely successful output. Unicode Chinese/Cyrillic paths are exercised.
- A real MCP stdio client initializes, discovers all 13 tools and calls the full chain,
  including model conversion/scaling/transformation, sections, DXF and XLSX/CSV export.
- DXF is reread/audited independently; Excel data and chart references are checked.

矩形箱体解析验证使用体积相对容差 `2e-6`、水线面积与稳心半径相对容差 `1e-4`。
这些是测试误差界限，不是程序替调用者选择的船型设计裕量。

The local validation record is generated in `docs/test-results.json`. It identifies
executed checks and records outstanding external acceptance conditions. CI definitions
are supplied; a workflow file is not evidence that GitHub CI or a separate clean VM has run.

Transformation acceptance requires an explicit displacement and LCB target supplied
by the caller. The server does not infer empirical targets or silently retain a
prototype value as a design requirement.
