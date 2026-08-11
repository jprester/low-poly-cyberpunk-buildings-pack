import { createReadStream, existsSync, statSync } from "node:fs";
import { dirname, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig, type Plugin, type PreviewServer, type ViteDevServer } from "vite";

const exampleRoot = dirname(fileURLToPath(import.meta.url));
const assetRootCandidates = [
  resolve(exampleRoot, "../../build/release/GLB"),
  resolve(exampleRoot, "../GLB"),
];
const developmentAssetRoot =
  assetRootCandidates.find((candidate) => existsSync(candidate)) ?? assetRootCandidates[0];

function attachAssetMiddleware(
  server: ViteDevServer | PreviewServer,
  mountPath: string,
): void {
  if (!existsSync(developmentAssetRoot)) {
    throw new Error(
      `Generated GLBs were not found. Checked: ${assetRootCandidates.join(", ")}`,
    );
  }

  server.middlewares.use(mountPath, (request, response, next) => {
    const rawPath = (request.url ?? "/").split("?", 1)[0];
    let requestPath: string;

    try {
      requestPath = decodeURIComponent(rawPath).replace(/^\/+/, "");
    } catch {
      response.statusCode = 400;
      response.end("Invalid asset path");
      return;
    }

    const filePath = resolve(developmentAssetRoot, requestPath);
    const isInsideAssetRoot =
      filePath === developmentAssetRoot || filePath.startsWith(`${developmentAssetRoot}${sep}`);

    if (!isInsideAssetRoot) {
      response.statusCode = 403;
      response.end("Asset path is outside the generated release directory");
      return;
    }

    if (!existsSync(filePath) || !statSync(filePath).isFile()) {
      next();
      return;
    }

    response.statusCode = 200;
    response.setHeader("Content-Type", "model/gltf-binary");
    response.setHeader("Cache-Control", "no-store");
    response.setHeader("Content-Length", statSync(filePath).size);

    if (request.method === "HEAD") {
      response.end();
      return;
    }

    createReadStream(filePath).pipe(response);
  });
}

function releaseAssetsPlugin(): Plugin {
  return {
    name: "release-assets",
    configureServer(server) {
      attachAssetMiddleware(server, "/release-assets");
    },
    configurePreviewServer(server) {
      attachAssetMiddleware(server, "/GLB");
    },
  };
}

export default defineConfig({
  base: "./",
  plugins: [releaseAssetsPlugin()],
  server: {
    host: "127.0.0.1",
    port: 4173,
    strictPort: true,
  },
  preview: {
    host: "127.0.0.1",
    port: 4173,
    strictPort: true,
  },
  build: {
    target: "es2022",
  },
});
