import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import "./styles.css";

type SmokeStatus = "loading" | "ready" | "error";

interface AssetDefinition {
  id: string;
  category: "Residential" | "Commercial" | "Skyscraper";
  filename: string;
}

interface AssetResult {
  id: string;
  category: string;
  grounded: boolean;
  meshCount: number;
  materialCount: number;
  pbrMaterialCount: number;
  emissiveMaterialCount: number;
  normalMapMaterialCount: number;
  boundsMetres: { width: number; depth: number; height: number };
}

interface SmokeReport {
  status: SmokeStatus;
  assetBaseUrl: string;
  assets: AssetResult[];
  errors: string[];
}

declare global {
  interface Window {
    __SMOKE_TEST__: SmokeReport;
  }
}

const canvas = requireElement<HTMLCanvasElement>("scene");
const statusElement = requireElement<HTMLSpanElement>("status");
const statusDot = requireElement<HTMLSpanElement>("status-dot");
const assetList = requireElement<HTMLDivElement>("asset-list");

const configuredAssetBase = import.meta.env.VITE_ASSET_BASE_URL?.trim();
const assetBaseUrl = (
  configuredAssetBase || (import.meta.env.DEV ? "/release-assets" : "../../GLB")
).replace(/\/$/, "");

const report: SmokeReport = {
  status: "loading",
  assetBaseUrl,
  assets: [],
  errors: [],
};
window.__SMOKE_TEST__ = report;

const assets: AssetDefinition[] = [
  { id: "RES_01", category: "Residential", filename: "RES_01.glb" },
  { id: "COM_06", category: "Commercial", filename: "COM_06.glb" },
  { id: "SKY_01", category: "Skyscraper", filename: "SKY_01.glb" },
];

const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.05;
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFShadowMap;

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x060a12);
scene.fog = new THREE.FogExp2(0x060a12, 0.00135);

const camera = new THREE.PerspectiveCamera(40, window.innerWidth / window.innerHeight, 0.1, 5000);
camera.position.set(180, 140, 260);

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.06;
controls.screenSpacePanning = false;

scene.add(new THREE.HemisphereLight(0x9dc9ff, 0x10141b, 2.1));

const keyLight = new THREE.DirectionalLight(0xe9f4ff, 3.2);
keyLight.position.set(-120, 220, 130);
keyLight.castShadow = true;
keyLight.shadow.mapSize.set(2048, 2048);
keyLight.shadow.camera.near = 1;
keyLight.shadow.camera.far = 800;
keyLight.shadow.camera.left = -250;
keyLight.shadow.camera.right = 250;
keyLight.shadow.camera.top = 300;
keyLight.shadow.camera.bottom = -100;
scene.add(keyLight);

const rimLight = new THREE.DirectionalLight(0x5ef5e6, 1.35);
rimLight.position.set(180, 80, -160);
scene.add(rimLight);

const buildingGroup = new THREE.Group();
scene.add(buildingGroup);

const grid = new THREE.GridHelper(700, 70, 0x2b948f, 0x172830);
grid.material.opacity = 0.26;
grid.material.transparent = true;
scene.add(grid);

const ground = new THREE.Mesh(
  new THREE.PlaneGeometry(700, 700),
  new THREE.MeshStandardMaterial({ color: 0x080d14, roughness: 0.92, metalness: 0.05 }),
);
ground.rotation.x = -Math.PI / 2;
ground.position.y = -0.04;
ground.receiveShadow = true;
scene.add(ground);

const loader = new GLTFLoader();

void loadAssets();
renderer.setAnimationLoop(render);
window.addEventListener("resize", resize);

async function loadAssets(): Promise<void> {
  try {
    const loaded = await Promise.all(
      assets.map(async (asset) => {
        const url = `${assetBaseUrl}/${asset.category}/${asset.filename}`;
        const gltf = await loader.loadAsync(url);
        const model = gltf.scene;
        model.name = asset.id;

        const initialBounds = new THREE.Box3().setFromObject(model);
        const initialCenter = initialBounds.getCenter(new THREE.Vector3());
        model.position.y -= initialBounds.min.y;
        model.position.z -= initialCenter.z;
        model.updateMatrixWorld(true);

        const groundedBounds = new THREE.Box3().setFromObject(model);
        const size = groundedBounds.getSize(new THREE.Vector3());
        const materialSummary = inspectMaterials(model);

        model.traverse((node) => {
          if (node instanceof THREE.Mesh) {
            node.castShadow = true;
            node.receiveShadow = true;
          }
        });

        return {
          asset,
          model,
          width: size.x,
          result: {
            id: asset.id,
            category: asset.category,
            grounded: Math.abs(groundedBounds.min.y) < 0.001,
            meshCount: materialSummary.meshCount,
            materialCount: materialSummary.materialCount,
            pbrMaterialCount: materialSummary.pbrMaterialCount,
            emissiveMaterialCount: materialSummary.emissiveMaterialCount,
            normalMapMaterialCount: materialSummary.normalMapMaterialCount,
            boundsMetres: {
              width: round(size.x),
              depth: round(size.z),
              height: round(size.y),
            },
          } satisfies AssetResult,
        };
      }),
    );

    const gap = 28;
    const totalWidth = loaded.reduce((sum, item) => sum + item.width, 0) + gap * (loaded.length - 1);
    let cursor = -totalWidth / 2;

    const compatibilityErrors = loaded.flatMap(({ result }) => {
      const errors: string[] = [];
      if (!result.grounded) errors.push(`${result.id} is not grounded at Y=0`);
      if (result.pbrMaterialCount === 0) errors.push(`${result.id} has no PBR material`);
      if (result.emissiveMaterialCount === 0) errors.push(`${result.id} has no emissive material`);
      if (result.normalMapMaterialCount === 0) errors.push(`${result.id} has no normal-mapped material`);
      return errors;
    });

    if (compatibilityErrors.length > 0) {
      throw new Error(compatibilityErrors.join("; "));
    }

    for (const item of loaded) {
      item.model.position.x += cursor + item.width / 2;
      item.model.updateMatrixWorld(true);
      buildingGroup.add(item.model);
      cursor += item.width + gap;
      report.assets.push(item.result);
      appendAssetCard(item.result);
    }

    frameScene(buildingGroup);
    report.status = "ready";
    statusElement.textContent = "3 / 3 assets loaded · compatibility checks passed";
    statusDot.className = "status-dot ready";
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    report.status = "error";
    report.errors.push(message);
    statusElement.textContent = `Load failed: ${message}`;
    statusDot.className = "status-dot error";
    console.error(error);
  }
}

function inspectMaterials(root: THREE.Object3D): Omit<AssetResult, "id" | "category" | "grounded" | "boundsMetres"> {
  const materials = new Map<string, THREE.Material>();
  let meshCount = 0;

  root.traverse((node) => {
    if (!(node instanceof THREE.Mesh)) return;
    meshCount += 1;
    const meshMaterials = Array.isArray(node.material) ? node.material : [node.material];
    for (const material of meshMaterials) materials.set(material.uuid, material);
  });

  const values = [...materials.values()];
  const pbrMaterials = values.filter(
    (material) => material instanceof THREE.MeshStandardMaterial || material instanceof THREE.MeshPhysicalMaterial,
  );

  return {
    meshCount,
    materialCount: values.length,
    pbrMaterialCount: pbrMaterials.length,
    emissiveMaterialCount: pbrMaterials.filter(
      (material) => material.emissiveMap !== null || material.emissive.getHex() !== 0,
    ).length,
    normalMapMaterialCount: pbrMaterials.filter((material) => material.normalMap !== null).length,
  };
}

function frameScene(root: THREE.Object3D): void {
  const bounds = new THREE.Box3().setFromObject(root);
  const center = bounds.getCenter(new THREE.Vector3());
  const size = bounds.getSize(new THREE.Vector3());
  const maxDimension = Math.max(size.x, size.y, size.z);
  const verticalFov = THREE.MathUtils.degToRad(camera.fov);
  const distance = (maxDimension / (2 * Math.tan(verticalFov / 2))) * 1.35;

  camera.position.set(center.x + distance * 0.72, center.y + distance * 0.48, center.z + distance);
  camera.near = Math.max(0.1, distance / 1000);
  camera.far = distance * 8;
  camera.updateProjectionMatrix();

  controls.target.copy(center);
  controls.maxDistance = distance * 3;
  controls.minDistance = Math.max(5, distance * 0.12);
  controls.update();
}

function appendAssetCard(asset: AssetResult): void {
  const card = document.createElement("div");
  card.className = "asset-card";
  card.dataset.assetId = asset.id;
  card.dataset.grounded = String(asset.grounded);
  card.dataset.pbrMaterials = String(asset.pbrMaterialCount);
  card.dataset.emissiveMaterials = String(asset.emissiveMaterialCount);
  card.dataset.normalMapMaterials = String(asset.normalMapMaterialCount);
  card.innerHTML = `
    <span class="asset-id">${asset.id}</span>
    <span class="asset-category">${asset.category}</span>
    <span class="asset-height">${asset.boundsMetres.height.toFixed(1)} m</span>
  `;
  assetList.append(card);
}

function render(): void {
  controls.update();
  renderer.render(scene, camera);
}

function resize(): void {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
}

function requireElement<T extends HTMLElement>(id: string): T {
  const element = document.getElementById(id);
  if (!element) throw new Error(`Required element #${id} was not found`);
  return element as T;
}

function round(value: number): number {
  return Math.round(value * 1000) / 1000;
}
