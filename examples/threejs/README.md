# Three.js compatibility example

This minimal Vite application loads one generated GLB from each building
category without changing its scale or material setup. It checks ground
placement and reports the PBR, emissive, and normal-map material counts through
`window.__SMOKE_TEST__` for browser smoke testing.

## Run from this repository

Generate the release GLBs first, then:

```sh
cd examples/threejs
npm install
npm run dev
```

Open `http://127.0.0.1:4173/`. The development server reads GLBs directly from
`build/release/GLB`; it does not copy or track the large generated assets.

The same commands work from `ThreeJS_Example/` in the packaged release. In
that layout, the development server automatically reads the sibling `GLB/`
directory.

Verify the production bundle with:

```sh
npm run build
```

The production build defaults to `../../GLB`, which is the expected relative
path when `dist/` is included as `ThreeJS_Example/dist/` in the final release.
Generated JavaScript and CSS URLs are relative, so the built example remains
portable when the release is hosted below a URL path.
For another layout, set `VITE_ASSET_BASE_URL` to the URL containing the category
directories before building.

For example:

```sh
VITE_ASSET_BASE_URL=/assets/GLB npm run build
```

Serve built files over HTTP; browsers should not load the example through a
`file://` URL.

To run the prebuilt example without installing npm packages, start a static
server from the root of the unpacked product:

```sh
python3 -m http.server 8000
```

Then open:

```text
http://127.0.0.1:8000/ThreeJS_Example/dist/
```
