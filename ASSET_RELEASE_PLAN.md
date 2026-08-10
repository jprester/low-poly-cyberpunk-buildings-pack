Asset Release Automation — Implementation Plan
Phase 1 — Repository Setup

Create automation incrementally. For Phases 1-2, create only:

automation/
├── blender/
│ ├── validate_assets.py
│ └── common.py
│
├── config/
│ └── release_config.json
│
└── README.md

Create later-phase directories and scripts only when their phase begins. Avoid
empty placeholder implementations that can be mistaken for working release
automation.

Add:

PROJECT_CONTEXT.md

to repository root.

Phase 2 — Asset Validator

Implement Blender-side validation.

Command concept:

blender --background Blender/low-poly-cyberpunk-buildings-pack.blend \
 --python-exit-code 2 \
 --python automation/blender/validate_assets.py

Output:

build/
└── validation_report.json

Example:

{
"status": "warning",
"assets": {
"RES_01": {
"errors": [],
"warnings": []
}
}
}

The report should include stable issue codes, per-asset and overall statuses,
summary counts, Blender/source metadata, and the measurements used by origin,
geometry, material, and texture checks. Validation must be read-only with
respect to the source `.blend`; only the JSON report may be written.

Do this before improving the exporter.

Phase 3 — Exporter

Begin only after Phase 2 reports zero errors. Warnings remain visible in the
validation report but do not block export.

Build on the already-proven individual GLB export workflow.

For every supported collection:

Residential
Commercial
Skyscraper

Export each mesh individually.

Requirements:

temporary world-origin relocation
restore original catalogue transform afterward
selected-object export only
no camera
no light
no unrelated objects
preserve materials
preserve textures
preserve UVs
preserve normals

Output:

build/release/GLB/...

Do not overwrite source assets.

Phase 4 — Manifest Generator

During the same Blender run, collect:

dimensions
vertices
triangles
materials
texture references
GLB file size

Generate:

asset_manifest.json
asset_manifest.csv

Use one internal JSON representation and derive CSV from it.

Avoid maintaining two independent implementations.

Generate both files from the exporter's fresh validation data and actual GLB
results during a complete export run. Partial `--asset` smoke tests must not
replace the full release manifest.

Phase 5 — Automated Preview Renderer

Implementation output:

build/release/Preview/<Category>/<ASSET_ID>_preview.png

Render from an unsaved temporary scene and write previews atomically. The
source catalogue must remain unchanged.

Generate standardized previews.

For every asset:

Duplicate/link into temporary preview scene.
Position origin at (0,0,0).
Determine bounds.
Automatically position camera based on bounds.
Render three-quarter perspective.
Save PNG.
Delete temporary preview instance.

Camera framing must adapt automatically to:

small residential buildings
medium commercial buildings
very tall skyscrapers

Do not hardcode camera distance per category if bounding-box framing can solve it.

Phase 6 — Collection Overview Renderer

Implementation output:

build/release/Preview/residential_collection.png
build/release/Preview/commercial_collection.png
build/release/Preview/skyscraper_collection.png

Use the same temporary studio as individual previews. Compute grid spacing from
category footprint bounds, align every linked copy to a common ground plane,
and frame the combined layout automatically.

Generate three overview images:

residential_collection.png
commercial_collection.png
skyscraper_collection.png

Automatically lay models out in rows with enough spacing to avoid overlap.

Prefer consistent ground alignment.

Phase 7 — Documentation Generator

Implementation output:

build/release/Documentation/README.md
build/release/Documentation/AI_DISCLOSURE.md

Keep product and usage copy in tracked Markdown templates. Inject calculated
statistics from the canonical JSON manifest, copy the AI disclosure template,
and reject absolute local paths in generated release documentation.

Do not invent license terms. An approved `LICENSE.txt` remains a required input
before packaging.

Read asset_manifest.json.

Generate README sections automatically:

number of buildings
building counts by category
triangle range
dimension ranges
included material families

Keep artistic/product copy in templates.

Do not generate excessive marketing language.

Phase 8 — Three.js Smoke Test

Implementation output:

examples/threejs/
├── package.json
├── index.html
├── vite.config.ts
└── src/
    ├── main.ts
    └── styles.css

Create minimal Vite + Three.js application.

Load at least:

one residential building
one commercial building
one skyscraper

Show:

correct scale
correct orientation
correct ground placement
PBR material
emissive output

Optional:

bloom toggle

Make this a simple compatibility demonstration.

During local development, serve the representative assets directly from
`build/release/GLB` instead of copying generated binaries into Git. The
production bundle assumes it will be placed at `ThreeJS_Example/dist` beside
the release `GLB` directory, with an environment-variable override available
for other hosting layouts.

The implemented smoke test loads `RES_01`, `COM_06`, and `SKY_01` at native
scale, grounds their evaluated bounds at Y=0, and fails its visible status if
any representative asset lacks PBR, emissive, or normal-mapped materials.
Browser verification completed with all three assets passing and no console
warnings or errors.

Phase 9 — Release Builder

Implementation output:

automation/scripts/build_release.py

Create one command:

python3 automation/scripts/build_release.py

The orchestrator should:

Clear temporary build directory.
Validate Blender source.
Stop if validation contains errors.
Export assets.
Generate manifest.
Render previews.
Generate documentation.
Copy source .blend.
Copy texture sources.
Copy Three.js example.
Generate release summary.
Create final ZIP.

Example final output:

dist/
├── Cyberpunk_Building_Pack_v1.0/
└── Cyberpunk_Building_Pack_v1.0.zip

Preflight all source files and external executables before clearing `build/`.
An approved `LICENSE.txt` is mandatory and must never be invented by the
automation. Assemble the release in a temporary directory under `dist/`, then
replace generated directory/ZIP outputs only after every stage and ZIP creation
succeeds. Preserve any previous generated release when a later step fails.

The implemented builder writes `build/release_build_report.json`, filters OS,
Blender-backup, Python-cache, Git, and JavaScript-dependency artifacts while
copying, and creates factual `RELEASE_NOTES.md` and `RELEASE_SUMMARY.json`
files. Its missing-license failure path was tested before the approved asset
license was added. The Three.js MIT license is preserved separately in
`THIRD_PARTY_NOTICES.txt`.
Phase 10 — Release Verification

Automate basic checks:

ZIP exists
every manifest asset has corresponding GLB
every GLB has non-zero size
every preview exists
README exists
AI disclosure exists
no absolute local file paths appear in documentation
no .DS_Store
no Blender backup files
no Python caches
no temporary build data

Produce:

release_report.txt

with final:

PASS

or:

FAIL.

Optional v1.1 Work

After v1 is published:

convert 4K textures to optimized 2K versions
external shared .gltf texture workflow
KTX2/Basis Three.js edition
texture memory statistics
LODs
additional preview styles
marketplace-specific metadata generation
automatic screenshots of Three.js demo
GitHub Actions / CI release build

Do not implement these before the core pipeline works.
