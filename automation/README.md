# Asset validation automation

Only Phase 1 (minimal setup) and Phase 2 (validation) are implemented. No
export, rendering, documentation generation, packaging, or source-asset repair
is performed here.

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
    └── GLB/
        ├── Residential/
        ├── Commercial/
        └── Skyscraper/
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
