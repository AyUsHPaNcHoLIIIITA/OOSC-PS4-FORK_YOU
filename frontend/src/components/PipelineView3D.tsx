import { useEffect, useRef, useState } from 'react';
import { Boxes, MousePointerClick, Orbit, Info } from 'lucide-react';

// three.js + OrbitControls are loaded at runtime from a pinned CDN via dynamic
// import (see three-cdn.d.ts). Nothing is added to package.json or the bundle;
// the browser fetches the module directly, so this stays fully additive.
const THREE_URL = 'https://esm.sh/three@0.171.0';
const ORBIT_URL = 'https://esm.sh/three@0.171.0/examples/jsm/controls/OrbitControls.js';

type Detail = { label: string; value: string };
type LayerSpec = {
  key: string;
  title: string;
  metric: string;
  subtitle: string;
  color: string; // hex, e.g. '#6366f1'
  details: Detail[];
};

// Derive the six real pipeline layers from live globalState. Every figure here
// is real data the engine produced — none of it is decorative.
function buildLayers(state: any): { layers: LayerSpec[]; hasData: boolean } {
  const scenarios: any[] = state?.scenarios || [];
  const runs: any[] = state?.runs || [];
  const verdicts: any[] = state?.verdicts || [];
  const tools: any[] = state?.tools || [];
  const analysis: any = state?.analysis || null;

  const pass = verdicts.filter((v) => v.outcome === 'PASS').length;
  const fail = verdicts.filter((v) => v.outcome === 'FAIL').length;
  const total = verdicts.length;
  const passRate = total ? pass / total : 0;
  const steps = runs.reduce((n, r) => n + ((r.steps || []).length), 0);

  const byCat: Record<string, number> = {};
  for (const s of scenarios) byCat[s.category] = (byCat[s.category] || 0) + 1;
  const catDetails: Detail[] = Object.entries(byCat).map(([k, v]) => ({
    label: k.replace(/_/g, ' '),
    value: String(v),
  }));

  const byFailCat: Record<string, number> = {};
  for (const v of verdicts)
    if (v.outcome === 'FAIL' && v.failure_category)
      byFailCat[v.failure_category] = (byFailCat[v.failure_category] || 0) + 1;
  const topFail = Object.entries(byFailCat).sort((a, b) => b[1] - a[1])[0];

  const bySev: Record<string, number> = {};
  for (const v of verdicts)
    if (v.outcome === 'FAIL') bySev[v.severity] = (bySev[v.severity] || 0) + 1;
  const sevDetails: Detail[] = ['critical', 'high', 'medium', 'low']
    .filter((s) => bySev[s])
    .map((s) => ({ label: s, value: String(bySev[s]) }));

  const grade =
    total === 0 ? '—'
      : passRate >= 0.9 ? 'A'
      : passRate >= 0.8 ? 'B'
      : passRate >= 0.7 ? 'C'
      : passRate >= 0.6 ? 'D'
      : 'F';

  const highRisk = analysis?.high_risk_tools?.length || 0;
  const domain = state?.agentDomain || analysis?.domain || '—';

  const layers: LayerSpec[] = [
    {
      key: 'threat',
      title: 'Threat Surface Discovery',
      metric: `${tools.length} tools`,
      subtitle: analysis ? `risk tier: ${analysis.risk_tier ?? '—'}` : 'not analyzed yet',
      color: '#6366f1',
      details: [
        { label: 'domain', value: String(domain) },
        { label: 'tools mapped', value: String(tools.length) },
        { label: 'high-risk tools', value: String(highRisk) },
        { label: 'risk tier', value: String(analysis?.risk_tier ?? '—') },
      ],
    },
    {
      key: 'scenarios',
      title: 'Scenario Generation',
      metric: `${scenarios.length}`,
      subtitle: 'adversarial scenarios',
      color: '#8b5cf6',
      details: catDetails.length ? catDetails : [{ label: 'generated', value: '0' }],
    },
    {
      key: 'sandbox',
      title: 'Sandbox Execution',
      metric: `${runs.length} runs`,
      subtitle: `${steps} agent steps replayed`,
      color: '#06b6d4',
      details: [
        { label: 'runs executed', value: String(runs.length) },
        { label: 'total agent steps', value: String(steps) },
        {
          label: 'samples / scenario',
          value: String(state?.samplesPerScenario ?? 1),
        },
      ],
    },
    {
      key: 'classifier',
      title: 'Classifier · rules + LLM judge',
      metric: `${total} verdicts`,
      subtitle: 'deterministic rules → judge',
      color: '#f59e0b',
      details: [
        { label: 'verdicts adjudicated', value: String(total) },
        { label: 'passed', value: String(pass) },
        { label: 'failed', value: String(fail) },
      ],
    },
    {
      key: 'verdicts',
      title: 'Verdicts',
      metric: total ? `${pass}✓ / ${fail}✗` : '—',
      subtitle: topFail ? `top failure: ${topFail[0]}` : 'no failures',
      color: fail > 0 ? '#f43f5e' : '#10b981',
      details: sevDetails.length ? sevDetails : [{ label: 'clean', value: 'no failures' }],
    },
    {
      key: 'scorecard',
      title: 'Reliability Scorecard',
      metric: grade,
      subtitle: total ? `${Math.round(passRate * 100)}% pass rate` : 'run pipeline to score',
      color: '#34d399',
      details: [
        { label: 'grade', value: grade },
        { label: 'pass rate', value: total ? `${Math.round(passRate * 100)}%` : '—' },
        { label: 'total evaluated', value: String(total) },
      ],
    },
  ];

  const hasData = scenarios.length + runs.length + verdicts.length > 0;
  return { layers, hasData };
}
type Hover = { i: number; x: number; y: number } | null;

export default function PipelineView3D({ state }: any) {
  const mountRef = useRef<HTMLDivElement | null>(null);
  const [hover, setHover] = useState<Hover>(null);
  const [failed, setFailed] = useState(false);
  const [ready, setReady] = useState(false);

  const { layers, hasData } = buildLayers(state);
  // Rebuild the scene only when the underlying data actually changes.
  const sig = layers.map((l) => l.metric + l.subtitle).join('|');

  useEffect(() => {
    let disposed = false;
    let cleanup = () => {};

    (async () => {
      let THREE: any, OrbitControls: any;
      try {
        THREE = await import(/* @vite-ignore */ THREE_URL);
        ({ OrbitControls } = await import(/* @vite-ignore */ ORBIT_URL));
      } catch (e) {
        console.error('[PipelineView3D] failed to load three.js from CDN', e);
        if (!disposed) setFailed(true);
        return;
      }
      const mount = mountRef.current;
      if (disposed || !mount) return;

      const width = mount.clientWidth;
      const height = mount.clientHeight;

      const scene = new THREE.Scene();
      scene.fog = new THREE.FogExp2(0x0b1020, 0.055);

      const camera = new THREE.PerspectiveCamera(46, width / height, 0.1, 100);
      camera.position.set(7.5, 4.5, 9.5);

      const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
      renderer.setSize(width, height);
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      mount.appendChild(renderer.domElement);

      const controls = new OrbitControls(camera, renderer.domElement);
      controls.enableDamping = true;
      controls.dampingFactor = 0.08;
      controls.autoRotate = true;
      controls.autoRotateSpeed = 0.9;
      controls.enablePan = false;
      controls.minDistance = 6;
      controls.maxDistance = 22;

      scene.add(new THREE.AmbientLight(0x8899ff, 0.9));
      const key = new THREE.DirectionalLight(0xffffff, 1.1);
      key.position.set(6, 12, 8);
      scene.add(key);
      const rim = new THREE.PointLight(0x6366f1, 40, 40);
      rim.position.set(-6, 2, -4);
      scene.add(rim);
      const warm = new THREE.PointLight(0xf43f5e, 20, 30);
      warm.position.set(6, -2, 4);
      scene.add(warm);

      const GAP = 1.55;
      const N = layers.length;
      const baseY = (i: number) => (i - (N - 1) / 2) * GAP;

      // A text label rendered to a canvas texture, shown as a camera-facing
      // sprite beside each slab so it stays readable from any orbit angle.
      const makeLabel = (title: string, metric: string, color: string) => {
        const c = document.createElement('canvas');
        c.width = 1024; c.height = 256;
        const g = c.getContext('2d')!;
        g.clearRect(0, 0, c.width, c.height);
        g.font = 'bold 92px Inter, system-ui, sans-serif';
        g.fillStyle = color;
        g.textBaseline = 'middle';
        g.fillText(metric, 24, 86);
        g.font = '500 44px Inter, system-ui, sans-serif';
        g.fillStyle = 'rgba(226,232,240,0.92)';
        g.fillText(title, 24, 176);
        const tex = new THREE.CanvasTexture(c);
        tex.anisotropy = 4;
        const mat = new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false });
        const sprite = new THREE.Sprite(mat);
        sprite.scale.set(4.2, 1.05, 1);
        return { sprite, tex };
      };

      const stack = new THREE.Group();
      scene.add(stack);
      const pickable: any[] = [];
      const groups: any[] = [];
      const disposables: any[] = [];

      layers.forEach((spec, i) => {
        const g = new THREE.Group();
        g.position.y = baseY(i);

        const geo = new THREE.BoxGeometry(4, 0.28, 4);
        const col = new THREE.Color(spec.color);
        const mat = new THREE.MeshStandardMaterial({
          color: col,
          emissive: col,
          emissiveIntensity: 0.35,
          metalness: 0.4,
          roughness: 0.35,
          transparent: true,
          opacity: 0.62,
        });
        const slab = new THREE.Mesh(geo, mat);
        slab.userData.index = i;
        g.add(slab);
        pickable.push(slab);
        disposables.push(geo, mat);

        const edgeGeo = new THREE.EdgesGeometry(geo);
        const edgeMat = new THREE.LineBasicMaterial({ color: col, transparent: true, opacity: 0.9 });
        g.add(new THREE.LineSegments(edgeGeo, edgeMat));
        disposables.push(edgeGeo, edgeMat);

        const { sprite, tex } = makeLabel(spec.title, spec.metric, spec.color);
        sprite.position.set(3.4, 0.15, 0);
        g.add(sprite);
        disposables.push(tex, sprite.material);

        stack.add(g);
        groups.push({ group: g, slab, mat, base: baseY(i) });
      });

      // Central glowing pillar the layers thread onto — the data spine.
      const pillarGeo = new THREE.CylinderGeometry(0.06, 0.06, GAP * N, 12);
      const pillarMat = new THREE.MeshBasicMaterial({ color: 0x8b93ff, transparent: true, opacity: 0.28 });
      stack.add(new THREE.Mesh(pillarGeo, pillarMat));
      disposables.push(pillarGeo, pillarMat);

      // Particles streaming upward along the spine — the data flowing through the
      // pipeline. A share are tinted red/green to match the real fail/pass ratio.
      const verdicts: any[] = state?.verdicts || [];
      const failN = verdicts.filter((v) => v.outcome === 'FAIL').length;
      const failFrac = verdicts.length ? failN / verdicts.length : 0;
      const P = 900;
      const top = (GAP * N) / 2;
      const positions = new Float32Array(P * 3);
      const colors = new Float32Array(P * 3);
      const speeds = new Float32Array(P);
      const cIndigo = new THREE.Color(0x8b93ff);
      const cPass = new THREE.Color(0x34d399);
      const cFail = new THREE.Color(0xf43f5e);
      for (let i = 0; i < P; i++) {
        positions[i * 3] = (Math.random() - 0.5) * 0.9;
        positions[i * 3 + 1] = (Math.random() - 0.5) * GAP * N;
        positions[i * 3 + 2] = (Math.random() - 0.5) * 0.9;
        speeds[i] = 0.006 + Math.random() * 0.02;
        const r = Math.random();
        const c = verdicts.length === 0 ? cIndigo : r < failFrac ? cFail : r < failFrac + 0.5 ? cPass : cIndigo;
        colors[i * 3] = c.r; colors[i * 3 + 1] = c.g; colors[i * 3 + 2] = c.b;
      }
      const pGeo = new THREE.BufferGeometry();
      pGeo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
      pGeo.setAttribute('color', new THREE.BufferAttribute(colors, 3));
      const pMat = new THREE.PointsMaterial({
        size: 0.075, vertexColors: true, transparent: true, opacity: 0.9,
        blending: THREE.AdditiveBlending, depthWrite: false,
      });
      const points = new THREE.Points(pGeo, pMat);
      stack.add(points);
      disposables.push(pGeo, pMat);

      // Raycast on pointer move → highlight the hovered slab and surface its real
      // data in an HTML tooltip.
      const raycaster = new THREE.Raycaster();
      const ndc = new THREE.Vector2();
      let hovered = -1;
      const onMove = (ev: PointerEvent) => {
        const rect = renderer.domElement.getBoundingClientRect();
        ndc.x = ((ev.clientX - rect.left) / rect.width) * 2 - 1;
        ndc.y = -((ev.clientY - rect.top) / rect.height) * 2 + 1;
        raycaster.setFromCamera(ndc, camera);
        const hit = raycaster.intersectObjects(pickable, false)[0];
        const idx = hit ? hit.object.userData.index : -1;
        if (idx !== hovered) {
          hovered = idx;
          controls.autoRotate = idx === -1;
          renderer.domElement.style.cursor = idx === -1 ? 'grab' : 'pointer';
        }
        if (idx === -1) setHover(null);
        else setHover({ i: idx, x: ev.clientX - rect.left, y: ev.clientY - rect.top });
      };
      const onLeave = () => { hovered = -1; controls.autoRotate = true; setHover(null); };
      renderer.domElement.addEventListener('pointermove', onMove);
      renderer.domElement.addEventListener('pointerleave', onLeave);

      const clock = new THREE.Clock();
      let raf = 0;
      const animate = () => {
        raf = requestAnimationFrame(animate);
        const t = clock.getElapsedTime();
        groups.forEach((g, i) => {
          const isHot = i === hovered;
          g.group.position.y = g.base + Math.sin(t * 0.7 + i) * 0.045;
          g.mat.emissiveIntensity += ((isHot ? 0.95 : 0.35) - g.mat.emissiveIntensity) * 0.12;
          const target = isHot ? 1.06 : 1;
          g.group.scale.x += (target - g.group.scale.x) * 0.12;
          g.group.scale.z += (target - g.group.scale.z) * 0.12;
        });
        const pos = pGeo.attributes.position;
        for (let i = 0; i < P; i++) {
          let y = pos.array[i * 3 + 1] + speeds[i];
          if (y > top) y = -top;
          pos.array[i * 3 + 1] = y;
        }
        pos.needsUpdate = true;
        controls.update();
        renderer.render(scene, camera);
      };
      animate();

      const ro = new ResizeObserver(() => {
        const w = mount.clientWidth, h = mount.clientHeight;
        if (!w || !h) return;
        camera.aspect = w / h;
        camera.updateProjectionMatrix();
        renderer.setSize(w, h);
      });
      ro.observe(mount);

      setReady(true);
      cleanup = () => {
        cancelAnimationFrame(raf);
        ro.disconnect();
        renderer.domElement.removeEventListener('pointermove', onMove);
        renderer.domElement.removeEventListener('pointerleave', onLeave);
        controls.dispose();
        disposables.forEach((d) => d.dispose && d.dispose());
        renderer.dispose();
        if (renderer.domElement.parentNode === mount) mount.removeChild(renderer.domElement);
      };
    })();

    return () => { disposed = true; cleanup(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sig]);

  const hovered = hover ? layers[hover.i] : null;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h2 className="text-lg font-bold text-white flex items-center space-x-2">
          <Boxes className="w-5 h-5 text-indigo-400" />
          <span>Pipeline · Exploded 3D View</span>
        </h2>
        <div className="flex items-center gap-4 text-xs text-slate-400">
          <span className="flex items-center gap-1.5"><Orbit className="w-3.5 h-3.5 text-indigo-400" /> drag to orbit · scroll to zoom</span>
          <span className="flex items-center gap-1.5"><MousePointerClick className="w-3.5 h-3.5 text-indigo-400" /> hover a layer for live data</span>
        </div>
      </div>

      <div className="glass rounded-2xl overflow-hidden shadow-lg relative" style={{ height: '68vh', minHeight: 460 }}>
        <div ref={mountRef} className="absolute inset-0" />

        {!ready && !failed && (
          <div className="absolute inset-0 flex items-center justify-center text-slate-400 font-mono text-sm">
            Initializing WebGL scene…
          </div>
        )}

        {failed && (
          <div className="absolute inset-0 flex items-center justify-center p-8">
            <div className="glass-dark rounded-xl p-6 max-w-md text-center space-y-2">
              <Info className="w-6 h-6 text-amber-400 mx-auto" />
              <div className="text-sm text-slate-200 font-semibold">3D view couldn't load the renderer</div>
              <div className="text-xs text-slate-400">
                The WebGL library is fetched from a CDN at runtime and the request was blocked.
                Every metric is still available on the Scorecard and Setup tabs.
              </div>
            </div>
          </div>
        )}

        {!hasData && ready && !failed && (
          <div className="absolute top-4 left-4 glass-dark rounded-lg px-3.5 py-2.5 max-w-xs pointer-events-none">
            <div className="text-xs text-slate-300 leading-relaxed">
              Layers show <span className="text-indigo-300 font-semibold">live</span> pipeline data.
              Run an evaluation on the <span className="font-semibold">Setup</span> tab to populate them.
            </div>
          </div>
        )}

        {hovered && hover && (
          <div
            className="absolute z-20 glass-dark rounded-xl p-3.5 pointer-events-none shadow-xl border border-white/10 w-56"
            style={{ left: Math.min(hover.x + 16, (mountRef.current?.clientWidth || 600) - 240), top: Math.max(hover.y - 20, 8) }}
          >
            <div className="flex items-center gap-2 mb-2">
              <span className="w-2.5 h-2.5 rounded-full" style={{ background: hovered.color }} />
              <span className="text-xs font-bold text-white">{hovered.title}</span>
            </div>
            <div className="space-y-1">
              {hovered.details.map((d, k) => (
                <div key={k} className="flex items-center justify-between text-[11px]">
                  <span className="text-slate-400 capitalize">{d.label}</span>
                  <span className="text-slate-100 font-mono font-semibold">{d.value}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}


