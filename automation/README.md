# Asset validation automation

Release automation is implemented incrementally through manifest generation,
individual and collection preview rendering, manifest-driven documentation,
and a Three.js compatibility example. Packaging and source-asset repair are
not performed here.

## Safety

The validator reads the open Blender file and writes one JSON report. It does
not call save operators, alter object data, apply transforms, or move catalogue
objects. The report is written atomically so an interrupted run does not leave
a partially written JSON file.

## Run from Blender's CLI

Run these commands from the repository root.

If `blender` is available on `PATH`:

```sh
blender --background Blender/low-poly-cyberpunk-buildings-pack.blend \
  --python-exit-code 2 \
  --python automation/blender/validate_assets.py
```

On macOS with the standard Blender application install:

```sh
/Applications/Blender.app/Contents/MacOS/Blender \
  --background Blender/low-poly-cyberpunk-buildings-pack.blend \
  --python-exit-code 2 \
  --python automation/blender/validate_assets.py
```

The default output is:

```text
build/validation_report.json
```

To choose another output path or configuration, pass validator arguments after
Blender's `--` separator. Relative paths are resolved from the repository root:

```sh
blender --background Blender/low-poly-cyberpunk-buildings-pack.blend \
  --python-exit-code 2 \
  --python automation/blender/validate_assets.py -- \
  --config automation/config/release_config.json \
  --output build/validation_report.json
```

By default Blender exits successfully when the validator ran successfully,
even when the report contains asset errors. This makes the report easy to
inspect manually. For build/CI gating, add `--fail-on-errors`; the report is
still written, then Blender exits with status 1 if validation errors exist:

```sh
blender --background Blender/low-poly-cyberpunk-buildings-pack.blend \
  --python-exit-code 2 \
  --python automation/blender/validate_assets.py -- --fail-on-errors
```

`--python-exit-code 2` makes Blender return a non-zero status if the validator
itself raises an unhandled Python exception.

## Report statuses

- `pass`: no errors or warnings
- `warning`: warnings exist, but no errors
- `error`: at least one release-blocking validation error exists

Each issue has a stable `code`, a human-readable `message`, and optional
machine-readable `details`. Thresholds and required PBR texture roles live in
`automation/config/release_config.json` so policy changes do not require code
changes.

## Export individual GLBs

Export begins by rerunning validation and stops without exporting if the report
contains any errors. Warnings do not block export. Outputs are restricted to
the repository's `build/` directory, and each GLB is written to a temporary
file before atomically replacing its generated destination.

```sh
blender --background Blender/low-poly-cyberpunk-buildings-pack.blend \
  --python-exit-code 2 \
  --python automation/blender/export_assets.py
```

Default outputs:

```text
build/
├── validation_report.json
├── export_report.json
└── release/
    ├── GLB/
    │   ├── Residential/
    │   ├── Commercial/
    │   └── Skyscraper/
    └── Manifest/
        ├── asset_manifest.json
        └── asset_manifest.csv
```

To smoke-test one or more assets, pass `--asset` after Blender's separator:

```sh
blender --background Blender/low-poly-cyberpunk-buildings-pack.blend \
  --python-exit-code 2 \
  --python automation/blender/export_assets.py -- \
  --asset RES_01 --asset COM_01
```

The exporter selects one object at a time, temporarily places its object origin
at world `0, 0, 0`, exports only that object, and restores the exact catalogue
world matrix and the original selection state. It does not save the `.blend`
or touch the existing top-level `GLB/` directory.

## Generate the release manifest

A complete export also writes JSON and CSV manifests during the same Blender
run. Both formats come from one canonical in-memory record list, so their asset
data cannot diverge through separate implementations. The manifest includes
dimensions, vertex and triangle counts, UV layers, materials, texture families,
texture references, validation status, and actual generated GLB sizes.

Partial runs using `--asset` deliberately skip manifest replacement, preventing
a smoke test from overwriting the complete 27-asset manifest.

## Render individual previews

The preview renderer creates an unsaved temporary Eevee studio scene, links one
asset copy at a time at world origin, frames the camera from evaluated bounds,
and atomically writes a square PNG. It deletes all temporary scene data before
Blender exits and never saves the catalogue.

```sh
blender --background Blender/low-poly-cyberpunk-buildings-pack.blend \
  --python-exit-code 2 \
  --python automation/blender/render_previews.py
```

Default outputs:

```text
build/
├── preview_report.json
└── release/
    └── Preview/
        ├── Residential/
        ├── Commercial/
        └── Skyscraper/
```

Use `--asset RES_01` after Blender's `--` separator for a targeted smoke test.
Resolution, camera lens, frame padding, view direction, background, and ground
colors are configured in `automation/config/release_config.json`.

## Render collection overviews

The overview renderer automatically arranges each category into centered rows,
using the largest footprint in that category to calculate collision-free cell
spacing. Asset copies are aligned to a common ground plane, framed from the
combined bounds, and removed after each render.

```sh
blender --background Blender/low-poly-cyberpunk-buildings-pack.blend \
  --python-exit-code 2 \
  --python automation/blender/render_collection_overviews.py
```

Default outputs:

```text
build/release/Preview/
├── residential_collection.png
├── commercial_collection.png
└── skyscraper_collection.png
```

Overview resolution and spacing are configured under `collection_overview` in
`automation/config/release_config.json`. Use `--category Residential` after
Blender's `--` separator to render only one configured category.

## Generate release documentation

Documentation generation is a standalone Python step; Blender is not required.
It reads the canonical JSON manifest, calculates pack statistics, fills the
README template, and copies the AI disclosure template.

```sh
python3 automation/scripts/generate_docs.py
```

Default outputs:

```text
build/
├── documentation_report.json
└── release/
    └── Documentation/
        ├── README.md
        └── AI_DISCLOSURE.md
```

Product and usage copy remains in `automation/templates/README.template.md`.
Counts, category ranges, material lists, and GLB size statistics are generated
from `build/release/Manifest/asset_manifest.json`.

License terms are not generated automatically. Supply an approved
`LICENSE.txt` before release packaging.

## Run the Three.js compatibility example

The Phase 8 example loads one generated residential, commercial, and
skyscraper GLB with Three.js. It preserves native dimensions, grounds each
model from its evaluated bounds, and checks for PBR, emissive, and normal-map
materials.

Generate the release GLBs first, then run:

```sh
cd examples/threejs
npm install
npm run dev
```

Open `http://127.0.0.1:4173/`. The development server reads directly from
`build/release/GLB`; generated GLBs are not copied into the tracked example.

Type-check and build the distributable web bundle with:

```sh
cd examples/threejs
npm run build
```

The build is written to ignored `examples/threejs/dist/`. See
`examples/threejs/README.md` for packaged-release paths and the
`VITE_ASSET_BASE_URL` override.

## Build the complete release

Phase 9 is orchestrated by one standalone Python command. Before deleting or
regenerating anything, it checks the Blender source, texture sources, Three.js
files, Blender executable, npm executable, automation scripts, and approved
license.

Run the non-destructive preflight first:

```sh
python3 automation/scripts/build_release.py --preflight-only
```

The approved asset license is tracked as `LICENSE.txt` at the repository root.
`THIRD_PARTY_NOTICES.txt` separately preserves the Three.js MIT notice. You may
point to an approved license stored elsewhere without copying it first:

```sh
python3 automation/scripts/build_release.py \
  --preflight-only \
  --license /absolute/path/to/approved-LICENSE.txt
```

The automation verifies only that the supplied file exists. Approval and the
legal accuracy of its terms remain a human responsibility.

After preflight passes, run the complete build:

```sh
python3 automation/scripts/build_release.py
```

The builder then:

1. Clears only the repository's generated `build/` directory.
2. Validates the Blender catalogue and stops on validation errors.
3. Exports every GLB and the canonical JSON/CSV manifest.
4. Renders individual previews and collection overviews.
5. Generates release documentation.
6. Builds the Three.js example from its lockfile in temporary build space.
7. Copies the Blender source, source textures, approved asset license,
   third-party notices, and generated outputs into a temporary release
   directory.
8. Generates `RELEASE_NOTES.md` and `RELEASE_SUMMARY.json`.
9. Creates the ZIP and atomically installs both final outputs.

Default outputs:

```text
dist/
├── Cyberpunk_Building_Pack_v1.0/
└── Cyberpunk_Building_Pack_v1.0.zip
```

Machine-readable pipeline status is written to
`build/release_build_report.json`. Existing `dist/` outputs are preserved if a
pipeline or ZIP stage fails. Generated copies omit `.DS_Store`, Blender backup
files, Python caches, `.git`, and `node_modules`.

If Blender is not detected automatically, use `--blender` or `BLENDER_BIN`:

```sh
python3 automation/scripts/build_release.py \
  --blender /Applications/Blender.app/Contents/MacOS/Blender
```

The asset license terms are a project-owner decision and should receive legal
review when appropriate. Phase 10 performs independent verification of the
completed directory and ZIP and has not started yet.
