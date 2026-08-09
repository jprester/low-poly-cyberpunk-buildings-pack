# Low-Poly Cyberpunk Buildings Pack — Project Context

## Product

**Low-Poly Cyberpunk Buildings Pack**

Optimized real-time cyberpunk building assets for Blender, glTF/GLB, Three.js and other real-time 3D engines.

Repository / project identifier:

`low-poly-cyberpunk-buildings-pack`

## Goal

Prepare an existing collection of lightweight cyberpunk building assets for commercial distribution.

The buildings use deliberately simple geometry combined with shared PBR texture atlases to provide substantially more visual detail than their polygon counts would normally suggest.

Primary strengths:

- Very lightweight geometry
- PBR materials
- Atlas-based facade detail
- Real-world scale
- Ground-centered origins
- Blender source files
- GLB exports
- Suitable for large city and skyline scenes
- Tested with Three.js
- Engine-agnostic asset design

Three.js support is a differentiator, not a restriction: the assets are intended to remain useful in Blender, game engines, visualization software and other glTF-compatible workflows.

# Asset Structure

The master Blender file contains three primary collections:

- `Residential`
- `Commercial`
- `Skyscraper`

Building object naming convention:

- `RES_01`, `RES_02`, ...
- `COM_01`, `COM_02`, ...
- `SKY_01`, `SKY_02`, ...

Mesh datablocks should ideally follow:

- `RES_01_Mesh`
- `COM_01_Mesh`
- `SKY_01_Mesh`

The master `.blend` is a catalogue scene. Buildings may be positioned around the scene for inspection.

Their catalogue location must NOT affect exported assets.

---

# Transform Convention

Every building should have:

- Scale = `1, 1, 1`
- Rotation = `0, 0, 0`
- Object origin located at the center of the building footprint at ground level

When exported individually, the building origin should be at world:

`0, 0, 0`

This allows runtime placement such as:

```js
building.position.set(x, 0, z);
```

without additional vertical offsets.

Do not destructively move objects inside the master catalogue scene just to export them.

The exporter may temporarily relocate objects and restore them afterward.

---

# Materials

Canonical material families currently include approximately:

- `MAT_Residential_Atlas`
- `MAT_Commercial_Atlas_A`
- `MAT_Commercial_Atlas_B`
- `MAT_Commercial_Atlas_C`
- `MAT_Industrial_Atlas`
- `MAT_Beacon_Red`

Commercial buildings and skyscrapers may intentionally share the same atlas materials.

Asset category and material family are separate concepts.

Avoid creating duplicate materials per building.

For example, do NOT generate:

- `MAT_Commercial_Atlas_A.001`
- `MAT_Commercial_Atlas_A.002`

if they are identical.

---

# PBR Material Convention

Base Color:

`Image Texture [sRGB] -> Principled BSDF Base Color`

Roughness:

`Image Texture [Non-Color] -> Principled BSDF Roughness`

Emission:

`Image Texture [sRGB] -> Principled BSDF Emission Color`

Normal:

`Image Texture [Non-Color] -> Normal Map node -> Principled BSDF Normal`

Typical normal strength is approximately:

`0.3–0.6`

Current assets generally use approximately `0.5`.

Do not connect tangent-space normal texture RGB data directly to the Principled Normal input.

---

# Texture Strategy

The models use shared texture atlases.

This is important to the design of the asset pack.

Most visual detail comes from:

- facade textures
- windows
- mechanical panels
- roof elements
- vents
- structural trim
- emissive lighting

rather than expensive geometry.

Some current texture sets are 4K and therefore make self-contained GLBs relatively large.

Do NOT treat texture compression or external shared-texture conversion as a blocker for the first automated release pipeline.

Future work may include:

- 2K versions
- WebP
- KTX2/Basis
- shared external `.gltf` textures
- packed ORM textures

Those are post-v1 optimizations.

---

# Asset Characteristics

The models are deliberately lightweight.

Their main product positioning should be:

"Optimized real-time cyberpunk building assets"

rather than simply:

"Low-poly buildings"

The intended uses include:

- Three.js
- React Three Fiber
- WebGL/WebGPU applications
- Blender
- game engines
- large background city environments
- skyline scenes
- distant/mid-distance assets

Three.js support is a differentiator, but the assets should remain engine-agnostic.

---

# Expected Release Package

The automation should ultimately produce something similar to:

```text
low-poly-cyberpunk-buildings-pack/
│
├── Blender/
│   └── cyberpunk_buildings.blend
│
├── GLB/
│   ├── Residential/
│   │   ├── RES_01.glb
│   │   └── ...
│   ├── Commercial/
│   │   ├── COM_01.glb
│   │   └── ...
│   └── Skyscraper/
│       ├── SKY_01.glb
│       └── ...
│
├── Textures/
│   ├── Residential/
│   ├── Commercial_A/
│   ├── Commercial_B/
│   ├── Commercial_C/
│   └── Industrial/
│
├── Manifest/
│   ├── asset_manifest.csv
│   └── asset_manifest.json
│
├── Preview/
│   ├── Residential/
│   ├── Commercial/
│   ├── Skyscraper/
│   └── Technical/
│
├── ThreeJS_Example/
│
├── Documentation/
│   ├── README.md
│   ├── LICENSE.txt
│   └── AI_DISCLOSURE.md
│
└── RELEASE_NOTES.md
```

---

# Manifest

Generate both CSV and JSON.

Each asset should include at least:

- ID
- category
- filename
- width
- depth
- height
- vertex count
- triangle count
- UV layer count
- material count
- material names
- texture family
- GLB file size

Example:

```json
{
  "id": "COM_04",
  "category": "Commercial",
  "width_m": 38.2,
  "depth_m": 31.4,
  "height_m": 112.7,
  "triangles": 840,
  "materials": ["MAT_Commercial_Atlas_B", "MAT_Beacon_Red"]
}
```

---

# Validation

Validation should run before export.

Validation errors should distinguish:

## Errors

Release should fail if:

- object has unapplied scale
- object has unapplied rotation
- object has no UV map
- required texture is missing
- broken image reference exists
- object name violates asset convention
- origin is clearly not at ground level
- export fails

## Warnings

Release may continue if:

- object origin is slightly off footprint center
- material is double-sided
- unusually high triangle count
- unusually large output file
- building has more material slots than expected
- texture resolution is unusually large

Generate a validation report.

Do NOT automatically "fix" artistic or structural issues without explicit permission.

---

# Preview Rendering

Automate standardized renders for every asset.

Prefer a consistent neutral presentation:

- dark or neutral background
- three-quarter camera
- consistent focal length
- consistent relative framing
- simple studio/environment lighting
- material preview enabled
- no dramatic depth of field

Each asset should get at least:

`RES_01_preview.png`

Optionally generate:

- beauty view
- wireframe/technical view

Also generate collection overview images for:

- Residential
- Commercial
- Skyscraper

These will be useful for marketplace listings.

---

# Three.js Verification

Create a minimal Three.js example.

It should:

- load representative GLBs
- use `GLTFLoader`
- use OrbitControls
- use appropriate color management
- use ACES tone mapping
- demonstrate emissive maps
- optionally demonstrate bloom
- place buildings on a flat ground plane

The example should be deliberately small.

Its purpose is to demonstrate compatibility, not reproduce the complete cyberpunk city project.

---

# Documentation

README should explain:

- what is included
- asset categories
- supported formats
- dimensions/scale convention
- coordinate/origin convention
- texture maps
- material setup
- importing into Blender
- importing GLB generally
- Three.js usage
- performance considerations
- shared atlas architecture

Do not claim compatibility that has not actually been tested.

---

# AI Disclosure

Some source texture artwork was produced with generative AI.

The release should disclose this clearly.

Suggested wording:

"Some source texture artwork in this asset pack was created with generative AI. Building models, topology, UV layouts, material setup, texture integration, optimization, testing and final asset preparation were performed manually."

Do not hide or minimize this disclosure.

Do not make AI generation the primary marketing message either.

---

# Non-Goals for v1

Do NOT delay the first release to implement:

- multiple LOD levels
- KTX2
- Basis compression
- Unreal-specific packages
- Unity packages
- procedural city generation
- multiple texture resolution tiers
- day/night texture variants
- collision meshes
- elaborate documentation site
- extensive refactoring of completed models

These can be added later if buyers find them useful.

---

# Safety Principle

The master `.blend` is the source of truth.

Automation must not destructively rewrite it.

Prefer:

- read-only validation
- temporary transform changes
- copied release files
- generated output directories

Never permanently modify model geometry or UVs during release automation without explicit instruction.
