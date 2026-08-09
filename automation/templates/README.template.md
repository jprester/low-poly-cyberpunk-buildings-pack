# Low-Poly Cyberpunk Buildings Pack

Optimized real-time cyberpunk building assets for Blender, glTF/GLB, Three.js,
game engines, visualization software, and other glTF-compatible workflows.

The pack combines lightweight geometry with shared PBR facade atlases. Most
architectural detail comes from the texture sets rather than expensive mesh
detail, making the buildings suitable for large city, skyline, background, and
mid-distance scenes.

{{GENERATED_ASSET_SUMMARY}}

## Included content

```text
Blender/       Master catalogue scene
GLB/           Individual buildings organized by category
Textures/      Shared source texture atlases
Manifest/      JSON and CSV asset metadata
Preview/       Individual previews and collection overviews
Documentation/ Release documentation and AI disclosure
```

## Scale, transforms, and placement

- Measurements use metres.
- Building scale is `1, 1, 1` and rotation is `0, 0, 0` in the Blender source.
- Each building origin is located at ground level near the center of its
  footprint.
- Individual GLBs are exported with their object origin at world `0, 0, 0`.
- The master Blender file is a catalogue scene, so catalogue object positions
  are not exported.

For Y-up runtimes such as Three.js, a building can be placed directly on the
ground without an additional vertical offset:

```js
building.position.set(x, 0, z);
```

## PBR materials and shared atlases

The assets reuse atlas materials across multiple buildings instead of creating
per-building material duplicates. Commercial buildings and skyscrapers may
intentionally share Commercial atlas families.

Texture roles include:

- Base Color — sRGB
- Roughness — Non-Color data
- Emission — sRGB
- Normal — Non-Color data through a Normal Map node

Normal-map strength is generally approximately `0.5`. The Residential atlas
includes Base Color, Roughness, Emission, and Normal maps.

Self-contained GLBs embed their required textures. Some atlases are 4K, so GLB
file sizes vary by material family.

## Blender usage

Open the master `.blend` to browse the complete catalogue and shared material
setup. To use a building in another Blender project, append or link the desired
object and its material dependencies from the source file.

The individual GLBs can also be imported with Blender's glTF importer.

## General GLB usage

Import the desired building from its category directory. Each GLB contains one
building mesh, its assigned materials, UVs, normals, and embedded textures. The
files do not contain catalogue cameras, lights, or unrelated objects.

## Three.js example

Use `GLTFLoader` and keep standard glTF color management enabled:

```js
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";

const loader = new GLTFLoader();
loader.load("./GLB/Residential/RES_01.glb", ({ scene }) => {
  scene.position.set(0, 0, 0);
  threeScene.add(scene);
});

renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
```

Add suitable scene lighting or environment lighting to display the PBR
materials. Emissive maps work without external texture assignment because they
are embedded in each GLB.

## Performance considerations

- Geometry is deliberately lightweight for real-time city and skyline scenes.
- Shared atlases reduce the number of unique source texture sets.
- Self-contained GLBs prioritize portability over minimum duplicated texture
  storage across files.
- The pack does not include automatic LODs, collision meshes, or compressed
  KTX2/Basis texture variants in this release.

## AI disclosure

See [AI_DISCLOSURE.md](AI_DISCLOSURE.md).
