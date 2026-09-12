import { useEffect, useRef } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

export type SceneSample = { depth: number; value: number; hole: number };
export type SceneLayers = { boreholes: boolean; assay: boolean; ore: boolean; geology: boolean; grid: boolean };
export type SceneView = 'orbit' | 'section' | 'plan';

type Props = {
  samples: SceneSample[];
  selectedDepth: number;
  onSelectDepth: (depth: number) => void;
  metric: 'grade' | 'uncertainty' | 'lithology';
  layers: SceneLayers;
  view: SceneView;
  playing: boolean;
  scenarioColor: string;
};

const depthScale = 0.042;
const holeOrigins = [
  new THREE.Vector3(-4.8, 4.5, 0.2),
  new THREE.Vector3(0, 4.8, 0),
  new THREE.Vector3(4.8, 4.3, -0.2),
];

function boreholeCurve(origin: THREE.Vector3, hole: number) {
  const points = [];
  for (let i = 0; i <= 8; i += 1) {
    const depth = i * 32;
    points.push(new THREE.Vector3(
      origin.x + Math.sin(i * 0.75 + hole) * 0.45,
      origin.y - depth * depthScale,
      origin.z + Math.cos(i * 0.57 + hole) * 0.42,
    ));
  }
  return new THREE.CatmullRomCurve3(points);
}

function assayColor(value: number, metric: Props['metric'], accent: THREE.Color) {
  if (metric === 'lithology') return new THREE.Color(value > 0.75 ? '#c88d64' : '#6f899b');
  if (metric === 'uncertainty') return new THREE.Color(value > 0.7 ? '#f07c72' : '#6fcac0');
  return accent.clone().lerp(new THREE.Color('#f3b66d'), Math.min(1, Math.max(0, value / 2.1)));
}

export default function SubsurfaceScene(props: Props) {
  const rootRef = useRef<HTMLDivElement>(null);
  const stateRef = useRef({ props, tick: 0 });
  stateRef.current.props = props;

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const scene = new THREE.Scene();
    scene.background = new THREE.Color('#07151d');
    scene.fog = new THREE.Fog('#07151d', 18, 34);
    const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 100);
    camera.position.set(13, 10, 15);
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, powerPreference: 'high-performance' });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.localClippingEnabled = true;
    root.replaceChildren(renderer.domElement);
    renderer.domElement.setAttribute('aria-label', 'Interactive three-dimensional drillhole reconstruction');
    renderer.domElement.dataset.sceneReady = 'true';

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.075;
    controls.minDistance = 7;
    controls.maxDistance = 31;
    controls.target.set(0, -1, 0);

    scene.add(new THREE.HemisphereLight('#b9e6ed', '#081820', 1.35));
    const key = new THREE.DirectionalLight('#f4d8a9', 2.8);
    key.position.set(7, 13, 8);
    scene.add(key);
    const rim = new THREE.PointLight('#38d7ca', 18, 18, 2);
    rim.position.set(-7, -1, 4);
    scene.add(rim);

    const world = new THREE.Group();
    const gridGroup = new THREE.Group();
    const geologyGroup = new THREE.Group();
    const holeGroup = new THREE.Group();
    const assayGroup = new THREE.Group();
    const oreGroup = new THREE.Group();
    const markerGroup = new THREE.Group();
    world.add(gridGroup, geologyGroup, holeGroup, assayGroup, oreGroup, markerGroup);
    scene.add(world);

    const floor = new THREE.Mesh(
      new THREE.CircleGeometry(12, 64),
      new THREE.MeshBasicMaterial({ color: '#0d2630', transparent: true, opacity: 0.4, side: THREE.DoubleSide }),
    );
    floor.rotation.x = -Math.PI / 2;
    floor.position.y = -6.1;
    gridGroup.add(floor);

    const slicePlane = new THREE.Mesh(
      new THREE.PlaneGeometry(14, 14),
      new THREE.MeshBasicMaterial({ color: '#efb56d', transparent: true, opacity: 0.055, side: THREE.DoubleSide, depthWrite: false }),
    );
    slicePlane.rotation.x = -Math.PI / 2;
    markerGroup.add(slicePlane);

    const verticalPlane = new THREE.Mesh(
      new THREE.PlaneGeometry(14, 13),
      new THREE.MeshBasicMaterial({ color: '#4ed5cc', transparent: true, opacity: 0.04, side: THREE.DoubleSide, depthWrite: false }),
    );
    verticalPlane.rotation.y = Math.PI / 2;
    verticalPlane.position.x = 0;
    geologyGroup.add(verticalPlane);

    const pickables: THREE.Object3D[] = [];
    const orbitPoints: THREE.Vector3[] = [];
    let streamers: THREE.Mesh[] = [];

    function clear(group: THREE.Group) {
      while (group.children.length) {
        const child = group.children.pop();
        if (!child) continue;
        child.traverse((node) => {
          const mesh = node as THREE.Mesh;
          if (mesh.geometry) mesh.geometry.dispose();
          const material = mesh.material as THREE.Material | THREE.Material[] | undefined;
          if (Array.isArray(material)) material.forEach((item) => item.dispose());
          else if (material) material.dispose();
        });
      }
    }

    function build() {
      const current = stateRef.current.props;
      clear(holeGroup);
      clear(assayGroup);
      clear(oreGroup);
      clear(gridGroup);
      clear(markerGroup);
      pickables.splice(0, pickables.length);
      streamers = [];
      const a = new THREE.Color(current.scenarioColor);

      if (current.layers.grid) {
        const grid = new THREE.GridHelper(18, 18, '#27515b', '#15313b');
        grid.position.y = -6.08;
        gridGroup.add(grid);
        const vertical = new THREE.GridHelper(13, 13, '#173944', '#102a33');
        vertical.rotation.x = Math.PI / 2;
        vertical.position.y = 0;
        gridGroup.add(vertical);
      }
      if (current.layers.geology) {
        const shell = new THREE.Mesh(
          new THREE.IcosahedronGeometry(5.2, 2),
          new THREE.MeshPhysicalMaterial({ color: '#244653', roughness: 0.82, metalness: 0.04, transparent: true, opacity: 0.18, wireframe: true }),
        );
        shell.scale.set(1.22, 0.74, 0.72);
        shell.position.set(0, -1.15, 0);
        geologyGroup.add(shell);
        const contact = new THREE.Mesh(
          new THREE.TorusGeometry(4.55, 0.025, 8, 128),
          new THREE.MeshBasicMaterial({ color: '#6fd8c8', transparent: true, opacity: 0.55 }),
        );
        contact.rotation.x = Math.PI / 2;
        contact.position.y = -2.1;
        geologyGroup.add(contact);
      }
      if (current.layers.ore) {
        const ore = new THREE.Mesh(
          new THREE.IcosahedronGeometry(3.15, 3),
          new THREE.MeshPhysicalMaterial({ color: '#eaa866', emissive: '#6d3418', emissiveIntensity: 0.42, roughness: 0.5, metalness: 0.12, transparent: true, opacity: 0.38, transmission: 0.06 }),
        );
        ore.scale.set(1.44, 0.56, 0.72);
        ore.position.set(0, -1.7, 0);
        ore.userData.kind = 'ore-shell';
        oreGroup.add(ore);
        const oreWire = new THREE.Mesh(
          new THREE.IcosahedronGeometry(3.22, 2),
          new THREE.MeshBasicMaterial({ color: '#f4bd72', transparent: true, opacity: 0.32, wireframe: true }),
        );
        oreWire.scale.set(1.44, 0.56, 0.72);
        oreWire.position.copy(ore.position);
        oreGroup.add(oreWire);
      }
      if (current.layers.boreholes) {
        holeOrigins.forEach((origin, hole) => {
          const curve = boreholeCurve(origin, hole);
          orbitPoints.push(...curve.getPoints(40));
          const tube = new THREE.Mesh(
            new THREE.TubeGeometry(curve, 64, 0.065, 8, false),
            new THREE.MeshPhysicalMaterial({ color: '#e4faf1', emissive: '#1aa996', emissiveIntensity: 0.35, roughness: 0.28, metalness: 0.15 }),
          );
          tube.userData.kind = 'borehole';
          holeGroup.add(tube);
          const collar = new THREE.Mesh(
            new THREE.CylinderGeometry(0.22, 0.3, 0.16, 20),
            new THREE.MeshStandardMaterial({ color: '#f4c375', emissive: '#6d3614', emissiveIntensity: 0.2 }),
          );
          collar.position.copy(origin);
          collar.position.y += 0.08;
          holeGroup.add(collar);
          for (let i = 0; i < 8; i += 1) {
            const bead = new THREE.Mesh(
              new THREE.SphereGeometry(0.105 + (i % 3) * 0.025, 12, 8),
              new THREE.MeshStandardMaterial({ color: '#bfe9dc', emissive: '#1b796f', emissiveIntensity: 0.36 }),
            );
            bead.position.copy(curve.getPointAt(i / 8));
            bead.userData.kind = 'survey-station';
            holeGroup.add(bead);
          }
        });
      }
      if (current.layers.assay) {
        current.samples.forEach((sample, index) => {
          const hole = sample.hole % holeOrigins.length;
          const curve = boreholeCurve(holeOrigins[hole], hole);
          const point = curve.getPointAt(Math.min(0.98, Math.max(0.02, sample.depth / 260)));
          const color = assayColor(sample.value, current.metric, a);
          const assay = new THREE.Mesh(
            new THREE.SphereGeometry(sample.depth === current.selectedDepth ? 0.19 : 0.12, 16, 12),
            new THREE.MeshPhysicalMaterial({ color, emissive: color, emissiveIntensity: sample.depth === current.selectedDepth ? 0.65 : 0.18, roughness: 0.32, metalness: 0.18 }),
          );
          assay.position.copy(point);
          assay.userData = { kind: 'assay', depth: sample.depth, value: sample.value, hole: hole + 1 };
          assayGroup.add(assay);
          pickables.push(assay);
          if (index % 3 === 0) {
            const halo = new THREE.Mesh(
              new THREE.SphereGeometry(0.28, 12, 8),
              new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.14, depthWrite: false }),
            );
            halo.position.copy(point);
            assayGroup.add(halo);
          }
        });
      }
      const streamCount = 18;
      for (let i = 0; i < streamCount; i += 1) {
        const dot = new THREE.Mesh(new THREE.SphereGeometry(0.07, 8, 6), new THREE.MeshBasicMaterial({ color: '#f5d28e' }));
        dot.userData.phase = i / streamCount;
        dot.userData.offset = (i % 3) * 0.3;
        markerGroup.add(dot);
        streamers.push(dot);
      }
      slicePlane.position.y = 4.5 - current.selectedDepth * depthScale;
      verticalPlane.visible = current.view === 'section';
      slicePlane.visible = current.view !== 'plan';
    }

    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();
    const onPointer = (event: PointerEvent) => {
      const rect = renderer.domElement.getBoundingClientRect();
      pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
      raycaster.setFromCamera(pointer, camera);
      const hit = raycaster.intersectObjects(pickables, false)[0];
      renderer.domElement.style.cursor = hit ? 'pointer' : 'grab';
      if (event.type === 'click' && hit) stateRef.current.props.onSelectDepth(Number(hit.object.userData.depth));
    };
    renderer.domElement.addEventListener('pointermove', onPointer);
    renderer.domElement.addEventListener('click', onPointer);

    const resize = () => {
      const width = Math.max(1, root.clientWidth);
      const height = Math.max(1, root.clientHeight);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      renderer.setSize(width, height, false);
    };
    const observer = new ResizeObserver(resize);
    observer.observe(root);
    resize();

    let frame = 0;
    let lastProps = '';
    const animate = (now: number) => {
      frame = requestAnimationFrame(animate);
      const current = stateRef.current.props;
      const propKey = [current.selectedDepth, current.metric, current.view, current.playing, current.layers.boreholes, current.layers.assay, current.layers.ore, current.layers.geology, current.layers.grid, current.scenarioColor, current.samples.length].join('|');
      if (propKey !== lastProps) {
        lastProps = propKey;
        build();
        if (current.view === 'plan') {
          camera.position.set(0, 16, 0.1);
          camera.lookAt(0, 0, 0);
          controls.target.set(0, -1, 0);
        } else if (current.view === 'section') {
          camera.position.set(0, 1.2, 17);
          camera.lookAt(0, -1, 0);
          controls.target.set(0, -1, 0);
        } else if (current.view === 'orbit') {
          camera.position.set(13, 10, 15);
          controls.target.set(0, -1, 0);
        }
      }
      const time = now * 0.001;
      if (current.playing) {
        oreGroup.rotation.y = Math.sin(time * 0.22) * 0.1;
        oreGroup.scale.setScalar(1 + Math.sin(time * 1.4) * 0.012);
        streamers.forEach((dot) => {
          const phase = (dot.userData.phase + time * 0.065 + dot.userData.offset) % 1;
          const lane = Math.floor(dot.userData.offset / 0.3);
          const curve = boreholeCurve(holeOrigins[lane], lane);
          dot.position.copy(curve.getPointAt(phase * 0.82 + 0.08));
          dot.position.x += Math.sin(time * 2 + lane) * 0.12;
        });
        stateRef.current.tick = Math.round(time * 1000);
        renderer.domElement.dataset.sceneTick = String(stateRef.current.tick);
      }
      controls.update();
      renderer.render(scene, camera);
    };
    build();
    frame = requestAnimationFrame(animate);

    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      renderer.domElement.removeEventListener('pointermove', onPointer);
      renderer.domElement.removeEventListener('click', onPointer);
      controls.dispose();
      renderer.dispose();
      root.replaceChildren();
    };
  }, []);

  return <div className="scene-host" ref={rootRef}><div className="scene-loading">Preparing WebGL reconstruction…</div></div>;
}
