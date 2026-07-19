/** three.js mesh viewer for STEP/IGES (via occt-import-js wasm), 3MF and
 *  WRL/VRML files, with a structure tree whose checkboxes toggle subelement
 *  visibility. Loaded lazily — three.js is ~600 kB.
 *
 *  occt-import-js is an emscripten UMD bundle that does not survive Vite's
 *  module pipeline, so it is loaded as a plain <script> from /occt/ (copied
 *  from node_modules by scripts/copy-occt.mjs).
 */
import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { ThreeMFLoader } from "three/examples/jsm/loaders/3MFLoader.js";
import { VRMLLoader } from "three/examples/jsm/loaders/VRMLLoader.js";

export type MeshFormat = "step" | "iges" | "3mf" | "wrl";

// ------------------------------------------------------------ occt loading

interface OcctMesh {
  name: string;
  color?: [number, number, number];
  attributes: { position: { array: number[] }; normal?: { array: number[] } };
  index: { array: number[] };
}

interface OcctNode {
  name: string;
  meshes: number[];
  children: OcctNode[];
}

interface OcctResult {
  success: boolean;
  root: OcctNode;
  meshes: OcctMesh[];
}

interface OcctModule {
  ReadStepFile(content: Uint8Array, params: null): OcctResult;
  ReadIgesFile(content: Uint8Array, params: null): OcctResult;
}

declare global {
  interface Window {
    occtimportjs?: (opts: { locateFile: (f: string) => string }) => Promise<OcctModule>;
  }
}

let occtPromise: Promise<OcctModule> | null = null;

function loadOcct(): Promise<OcctModule> {
  if (occtPromise) return occtPromise;
  occtPromise = new Promise<OcctModule>((resolve, reject) => {
    const init = () => {
      if (!window.occtimportjs) {
        reject(new Error("occt-import-js failed to initialize"));
        return;
      }
      window
        .occtimportjs({ locateFile: () => "/occt/occt-import-js.wasm" })
        .then(resolve, reject);
    };
    if (window.occtimportjs) {
      init();
      return;
    }
    const script = document.createElement("script");
    script.src = "/occt/occt-import-js.js";
    script.onload = init;
    script.onerror = () => reject(new Error("failed to load /occt/occt-import-js.js"));
    document.head.appendChild(script);
  });
  occtPromise.catch(() => {
    occtPromise = null; // allow a retry on next mount
  });
  return occtPromise;
}

// ----------------------------------------------------------- model builders

const DEFAULT_COLOR = new THREE.Color(0x8a97a8);

function occtMaterial(color?: [number, number, number]): THREE.MeshStandardMaterial {
  const c = color
    ? new THREE.Color(...(color.some((v) => v > 1) ? color.map((v) => v / 255) : color) as [
        number,
        number,
        number,
      ])
    : DEFAULT_COLOR;
  return new THREE.MeshStandardMaterial({ color: c, metalness: 0.1, roughness: 0.65 });
}

function buildOcctObject(result: OcctResult): THREE.Group {
  const build = (node: OcctNode): THREE.Group => {
    const group = new THREE.Group();
    group.name = node.name;
    for (const idx of node.meshes) {
      const m = result.meshes[idx];
      if (!m) continue;
      const geo = new THREE.BufferGeometry();
      geo.setAttribute(
        "position",
        new THREE.BufferAttribute(Float32Array.from(m.attributes.position.array), 3),
      );
      if (m.attributes.normal) {
        geo.setAttribute(
          "normal",
          new THREE.BufferAttribute(Float32Array.from(m.attributes.normal.array), 3),
        );
      } else {
        geo.computeVertexNormals();
      }
      geo.setIndex(new THREE.BufferAttribute(Uint32Array.from(m.index.array), 1));
      const mesh = new THREE.Mesh(geo, occtMaterial(m.color));
      mesh.name = m.name;
      group.add(mesh);
    }
    for (const child of node.children) group.add(build(child));
    return group;
  };
  return build(result.root);
}

async function loadModel(url: string, format: MeshFormat): Promise<THREE.Object3D> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`file fetch failed (HTTP ${res.status})`);
  const buf = await res.arrayBuffer();

  if (format === "step" || format === "iges") {
    const occt = await loadOcct();
    const data = new Uint8Array(buf);
    const result = format === "step" ? occt.ReadStepFile(data, null) : occt.ReadIgesFile(data, null);
    if (!result.success) throw new Error("OpenCascade could not parse this file");
    return buildOcctObject(result);
  }
  if (format === "3mf") {
    return new ThreeMFLoader().parse(buf);
  }
  // wrl — VRMLLoader wants text
  const text = new TextDecoder().decode(buf);
  return new VRMLLoader().parse(text, "");
}

// ------------------------------------------------------------ subelem tree

export interface TreeEntry {
  id: string;
  label: string;
  depth: number;
  object: THREE.Object3D;
}

/** Flattened structure tree (depth-indented). Unnamed single-child wrapper
 *  groups are skipped so the tree mirrors what the user thinks of as parts. */
function buildTree(root: THREE.Object3D): TreeEntry[] {
  const out: TreeEntry[] = [];
  let anon = 0;
  const visit = (obj: THREE.Object3D, depth: number) => {
    const isLeafMesh = (obj as THREE.Mesh).isMesh === true;
    const skip = !obj.name && obj.children.length === 1 && !isLeafMesh;
    if (!skip) {
      const label = obj.name || (isLeafMesh ? `mesh ${++anon}` : `group ${++anon}`);
      out.push({ id: obj.uuid, label, depth, object: obj });
      depth += 1;
    }
    for (const child of obj.children) visit(child, depth);
  };
  for (const child of root.children) visit(child, 0);
  // Single root entry showing the whole model is noise; likewise a tree with
  // hundreds of anonymous meshes (tessellated VRML) is unusable — cap it.
  return out.length > 400 ? out.slice(0, 400) : out;
}

// -------------------------------------------------------------- component

export default function MeshView({ url, format }: { url: string; format: MeshFormat }) {
  const mountRef = useRef<HTMLDivElement | null>(null);
  const renderRef = useRef<(() => void) | null>(null);
  const [tree, setTree] = useState<TreeEntry[]>([]);
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [message, setMessage] = useState("");

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;

    let disposed = false;
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 1000);
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(window.devicePixelRatio);
    mount.appendChild(renderer.domElement);

    scene.add(new THREE.HemisphereLight(0xffffff, 0x60686f, 2.4));
    const key = new THREE.DirectionalLight(0xffffff, 1.6);
    key.position.set(1, 2, 1.5);
    scene.add(key);
    const fill = new THREE.DirectionalLight(0xffffff, 0.7);
    fill.position.set(-1.5, -1, -1);
    scene.add(fill);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = false;

    const render = () => {
      if (!disposed) renderer.render(scene, camera);
    };
    renderRef.current = render;
    controls.addEventListener("change", render);

    const resize = () => {
      const w = mount.clientWidth;
      const h = mount.clientHeight;
      if (w === 0 || h === 0) return;
      renderer.setSize(w, h);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      render();
    };
    const ro = new ResizeObserver(resize);
    ro.observe(mount);
    resize();

    setStatus("loading");
    setTree([]);
    setHidden(new Set());

    loadModel(url, format)
      .then((object) => {
        if (disposed) return;
        // Center the model and pull the camera back far enough to frame it.
        const box = new THREE.Box3().setFromObject(object);
        const center = box.getCenter(new THREE.Vector3());
        const size = box.getSize(new THREE.Vector3());
        const maxDim = Math.max(size.x, size.y, size.z) || 1;
        object.position.sub(center);
        scene.add(object);
        camera.near = maxDim / 100;
        camera.far = maxDim * 100;
        camera.position.set(maxDim * 0.9, maxDim * 0.8, maxDim * 1.2);
        camera.updateProjectionMatrix();
        controls.target.set(0, 0, 0);
        controls.update();
        setTree(buildTree(object));
        setStatus("ready");
        render();
      })
      .catch((err: unknown) => {
        if (disposed) return;
        setMessage(err instanceof Error ? err.message : String(err));
        setStatus("error");
      });

    return () => {
      disposed = true;
      renderRef.current = null;
      ro.disconnect();
      controls.dispose();
      renderer.dispose();
      scene.traverse((obj) => {
        const mesh = obj as THREE.Mesh;
        if (mesh.isMesh) {
          mesh.geometry.dispose();
          const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
          mats.forEach((m) => m.dispose());
        }
      });
      mount.removeChild(renderer.domElement);
    };
  }, [url, format]);

  const toggle = (entry: TreeEntry) => {
    setHidden((prev) => {
      const next = new Set(prev);
      if (next.has(entry.id)) {
        next.delete(entry.id);
        entry.object.visible = true;
      } else {
        next.add(entry.id);
        entry.object.visible = false;
      }
      renderRef.current?.();
      return next;
    });
  };

  return (
    <div className="meshview">
      <div ref={mountRef} className="meshview-canvas">
        {status === "loading" ? (
          <span className="meshview-status">Parsing model…</span>
        ) : status === "error" ? (
          <span className="meshview-status err-text">{message}</span>
        ) : null}
      </div>
      {status === "ready" && tree.length > 0 ? (
        <aside className="meshview-side">
          <h3>Structure</h3>
          <ul>
            {tree.map((entry) => (
              <li key={entry.id} style={{ paddingLeft: `${entry.depth * 14}px` }}>
                <label className="meshview-item" title={entry.label}>
                  <input
                    type="checkbox"
                    checked={!hidden.has(entry.id)}
                    onChange={() => toggle(entry)}
                  />
                  <span>{entry.label}</span>
                </label>
              </li>
            ))}
          </ul>
        </aside>
      ) : null}
    </div>
  );
}
