import { useEffect, useRef, useState } from 'react';
import { ChevronDown } from 'lucide-react';

// three.js is loaded at runtime from a pinned CDN (see three-cdn.d.ts) so nothing
// is added to package.json or the bundle. If the CDN or WebGL is unavailable the
// hero degrades to a CSS glow so the landing never renders blank.
const THREE_URL = 'https://esm.sh/three@0.171.0';

const clamp = (v: number, a: number, b: number) => Math.max(a, Math.min(b, v));

function scrollToApp() {
  document.getElementById('app-start')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

export default function BrainHero() {
  const wrapRef = useRef<HTMLDivElement | null>(null);  // tall pinned-scroll spacer
  const mountRef = useRef<HTMLDivElement | null>(null); // canvas host
  const copyRef = useRef<HTMLDivElement | null>(null);  // headline overlay (fades on scroll)
  const [failed, setFailed] = useState(false);
  // Respect prefers-reduced-motion: skip WebGL + scroll-pinning entirely and show
  // the static on-brand glow instead (also drives the shorter 100vh layout).
  const [reduced] = useState(
    () => typeof window !== 'undefined'
      && typeof window.matchMedia === 'function'
      && window.matchMedia('(prefers-reduced-motion: reduce)').matches,
  );
  const staticHero = failed || reduced;

  useEffect(() => {
    if (reduced) return; // static hero — no canvas, no listeners, no RAF loop
    let disposed = false;
    let cleanup = () => {};

    (async () => {
      let THREE: any;
      try {
        THREE = await import(/* @vite-ignore */ THREE_URL);
      } catch (e) {
        console.error('[BrainHero] three.js CDN load failed', e);
        if (!disposed) setFailed(true);
        return;
      }
      const mount = mountRef.current;
      if (disposed || !mount) return;

      const width = mount.clientWidth || window.innerWidth;
      const height = mount.clientHeight || window.innerHeight;

      const scene = new THREE.Scene();
      scene.fog = new THREE.FogExp2(0x05070f, 0.16);
      const camera = new THREE.PerspectiveCamera(50, width / height, 0.1, 100);
      camera.position.set(0, 0.15, 3.6);

      let renderer: any;
      try {
        renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
      } catch (e) {
        console.error('[BrainHero] WebGL unavailable', e);
        if (!disposed) setFailed(true);
        return;
      }
      renderer.setSize(width, height);
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      renderer.domElement.style.display = 'block';
      mount.appendChild(renderer.domElement);

      const group = new THREE.Group();
      scene.add(group);

      // ---------- brain-shaped cortex point cloud ----------
      // Two hemispheres split by a longitudinal fissure, a wrinkled cortex (gyri /
      // sulci) via layered turbulence, flattened underside + wider temporal lobes,
      // and a cerebellum tucked at the back-bottom. Axes: x = left/right (narrow),
      // y = up/down, z = front/back (longest).
      const cLow = new THREE.Color('#4f46e5');   // indigo — sulci / depth
      const cMid = new THREE.Color('#c026d3');   // fuchsia — mid
      const cHigh = new THREE.Color('#fb7185');  // rose — gyri crown

      const turb = (t: number, p: number) =>
        0.13 * Math.sin(9 * t) * Math.sin(8 * p)
        + 0.09 * Math.sin(17 * p + 3 * t)
        + 0.06 * Math.sin(15 * t - 4 * p)
        + 0.04 * Math.cos(25 * p) * Math.sin(21 * t);

      const cortexPoint = (): { pos: [number, number, number]; fold: number } => {
        const u = Math.random(), v = Math.random();
        const theta = 2 * Math.PI * u;
        const phi = Math.acos(2 * v - 1);
        const f = turb(theta, phi);
        const r = 1 + f;
        let x = r * Math.sin(phi) * Math.cos(theta) * 0.92;
        let y = r * Math.cos(phi) * 0.86;
        const z = r * Math.sin(phi) * Math.sin(theta) * 1.24;
        // longitudinal fissure: carve a groove down the top midline
        const groove = Math.exp(-(x * x) * 26) * clamp((y + 0.15) * 1.4, 0, 1);
        x += Math.sign(x || 1) * groove * 0.1;
        y -= groove * 0.14;
        if (y < 0) { y *= 0.66; x *= 1.06; } // flatten underside, widen temporal lobes
        return { pos: [x, y, z], fold: f };
      };

      const small = window.innerWidth < 640;      // lighter cloud on phones
      const CORTEX = small ? 9000 : 20000;
      const CEREB = small ? 1400 : 3000;
      const TOTAL = CORTEX + CEREB;
      const positions = new Float32Array(TOTAL * 3);
      const colors = new Float32Array(TOTAL * 3);
      const tmp = new THREE.Color();

      for (let i = 0; i < CORTEX; i++) {
        const { pos, fold } = cortexPoint();
        positions[i * 3] = pos[0]; positions[i * 3 + 1] = pos[1]; positions[i * 3 + 2] = pos[2];
        // colour by fold height: deep sulci → indigo, raised gyri → rose
        const h = clamp((fold + 0.18) / 0.36, 0, 1);
        if (h < 0.5) tmp.copy(cLow).lerp(cMid, h * 2);
        else tmp.copy(cMid).lerp(cHigh, (h - 0.5) * 2);
        colors[i * 3] = tmp.r; colors[i * 3 + 1] = tmp.g; colors[i * 3 + 2] = tmp.b;
      }
      // cerebellum: tight horizontal foliation at the back-underside
      for (let i = CORTEX; i < TOTAL; i++) {
        const u = Math.random(), v = Math.random();
        const theta = 2 * Math.PI * u, phi = Math.acos(2 * v - 1);
        const r = 0.46 * (1 + 0.16 * Math.sin(22 * phi) + 0.06 * Math.sin(9 * theta));
        const x = r * Math.sin(phi) * Math.cos(theta) * 1.15;
        const y = r * Math.cos(phi) * 0.62 - 0.66;
        const z = r * Math.sin(phi) * Math.sin(theta) * 0.82 - 1.02;
        positions[i * 3] = x; positions[i * 3 + 1] = y; positions[i * 3 + 2] = z;
        tmp.copy(cLow).lerp(cHigh, 0.3 + Math.random() * 0.2);
        colors[i * 3] = tmp.r; colors[i * 3 + 1] = tmp.g; colors[i * 3 + 2] = tmp.b;
      }

      const geo = new THREE.BufferGeometry();
      geo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
      geo.setAttribute('color', new THREE.BufferAttribute(colors, 3));
      const mat = new THREE.PointsMaterial({
        size: 0.016, vertexColors: true, transparent: true, opacity: 0.92,
        blending: THREE.AdditiveBlending, depthWrite: false,
      });
      const cortex = new THREE.Points(geo, mat);
      group.add(cortex);

      // ---------- neurons: bright somas + axon links + firing pulses ----------
      const NEUR = 70;
      const nodeIdx: number[] = [];
      for (let i = 0; i < NEUR; i++) nodeIdx.push(Math.floor(Math.random() * CORTEX));
      const nodePos = nodeIdx.map(
        (k) => new THREE.Vector3(positions[k * 3], positions[k * 3 + 1], positions[k * 3 + 2]),
      );

      // somas — the neuron cell bodies (bigger, bright cyan, twinkling)
      const somaPos = new Float32Array(NEUR * 3);
      nodePos.forEach((p: any, i: number) => { somaPos[i * 3] = p.x; somaPos[i * 3 + 1] = p.y; somaPos[i * 3 + 2] = p.z; });
      const somaGeo = new THREE.BufferGeometry();
      somaGeo.setAttribute('position', new THREE.BufferAttribute(somaPos, 3));
      const somaMat = new THREE.PointsMaterial({
        color: 0x67e8f9, size: 0.055, transparent: true, opacity: 0.95,
        blending: THREE.AdditiveBlending, depthWrite: false,
      });
      group.add(new THREE.Points(somaGeo, somaMat));

      // axons — connect each neuron to its two nearest neighbours
      const edges: [number, number][] = [];
      for (let i = 0; i < NEUR; i++) {
        const near = nodePos
          .map((p: any, j: number) => ({ j, d: p.distanceTo(nodePos[i]) }))
          .filter((o: any) => o.j !== i)
          .sort((a: any, b: any) => a.d - b.d);
        for (let k = 0; k < 2 && k < near.length; k++) {
          const j = near[k].j;
          if (!edges.some(([a, b]) => (a === i && b === j) || (a === j && b === i))) edges.push([i, j]);
        }
      }
      const elp = new Float32Array(edges.length * 6);
      edges.forEach(([a, b], i) => {
        elp[i * 6] = nodePos[a].x; elp[i * 6 + 1] = nodePos[a].y; elp[i * 6 + 2] = nodePos[a].z;
        elp[i * 6 + 3] = nodePos[b].x; elp[i * 6 + 4] = nodePos[b].y; elp[i * 6 + 5] = nodePos[b].z;
      });
      const elgeo = new THREE.BufferGeometry();
      elgeo.setAttribute('position', new THREE.BufferAttribute(elp, 3));
      const elmat = new THREE.LineBasicMaterial({
        color: 0x818cf8, transparent: true, opacity: 0.22,
        blending: THREE.AdditiveBlending, depthWrite: false,
      });
      group.add(new THREE.LineSegments(elgeo, elmat));

      // firing pulses — bright signals travelling along the axons
      const PULSE = 44;
      const pulsePos = new Float32Array(PULSE * 3);
      const pulse = Array.from({ length: PULSE }, () => ({
        e: Math.floor(Math.random() * edges.length), t: Math.random(), sp: 0.006 + Math.random() * 0.02,
      }));
      const pulseGeo = new THREE.BufferGeometry();
      pulseGeo.setAttribute('position', new THREE.BufferAttribute(pulsePos, 3));
      const pulseMat = new THREE.PointsMaterial({
        color: 0xffffff, size: 0.05, transparent: true, opacity: 0.95,
        blending: THREE.AdditiveBlending, depthWrite: false,
      });
      group.add(new THREE.Points(pulseGeo, pulseMat));

      // soft inner glow core
      const coreGeo = new THREE.SphereGeometry(0.5, 24, 24);
      const coreMat = new THREE.MeshBasicMaterial({ color: 0x3730a3, transparent: true, opacity: 0.12, blending: THREE.AdditiveBlending });
      group.add(new THREE.Mesh(coreGeo, coreMat));
      group.rotation.y = -0.4;

      // pointer parallax
      let targetRX = 0, targetRY = -0.4;
      const onMove = (ev: PointerEvent) => {
        const r = renderer.domElement.getBoundingClientRect();
        const nx = ((ev.clientX - r.left) / r.width) * 2 - 1;
        const ny = ((ev.clientY - r.top) / r.height) * 2 - 1;
        targetRY = -0.4 + nx * 0.45;
        targetRX = ny * 0.25;
      };
      window.addEventListener('pointermove', onMove);

      // scroll-driven reveal: progress 0→1 as the pinned section is scrolled through
      let progress = 0;
      const onScroll = () => {
        const el = wrapRef.current; if (!el) return;
        const span = el.offsetHeight - window.innerHeight;
        progress = span > 0 ? clamp(-el.getBoundingClientRect().top / span, 0, 1) : 0;
        if (copyRef.current) {
          const cp = clamp(1 - progress / 0.34, 0, 1);
          copyRef.current.style.opacity = String(cp);
          copyRef.current.style.transform = `translateY(${(-progress * 60).toFixed(1)}px)`;
        }
      };
      window.addEventListener('scroll', onScroll, { passive: true });
      onScroll();

      const clock = new THREE.Clock();
      let raf = 0;
      const animate = () => {
        raf = requestAnimationFrame(animate);
        // ease-in the fly-through so the handoff to the dashboard feels like a
        // deliberate dive rather than a linear scrub, and fade the canvas out over
        // the last stretch so the dashboard reveals underneath it.
        const eased = progress * progress;
        const canvasOp = 1 - clamp((progress - 0.55) / 0.4, 0, 1);
        renderer.domElement.style.opacity = String(canvasOp);
        if (canvasOp <= 0.01) return; // fully hidden — skip the draw
        const t = clock.getElapsedTime();
        camera.position.z = 3.6 - eased * 2.8;   // dolly "through" the brain
        group.scale.setScalar(1 + eased * 0.55); // and swell as we dive in
        group.rotation.y += (targetRY - group.rotation.y) * 0.05 + 0.0012;
        group.rotation.x += (targetRX - group.rotation.x) * 0.05;
        group.position.y = Math.sin(t * 0.5) * 0.025;
        mat.opacity = 0.85 + Math.sin(t * 1.5) * 0.1;
        somaMat.opacity = 0.7 + (Math.sin(t * 3) * 0.5 + 0.5) * 0.3;      // somas twinkle
        elmat.opacity = 0.14 + (Math.sin(t * 2) * 0.5 + 0.5) * 0.14;      // axons glow
        for (let i = 0; i < PULSE; i++) {
          const pu = pulse[i];
          pu.t += pu.sp;
          if (pu.t > 1) { pu.t = 0; pu.e = Math.floor(Math.random() * edges.length); }
          const [a, b] = edges[pu.e];
          const A = nodePos[a], B = nodePos[b];
          pulsePos[i * 3] = A.x + (B.x - A.x) * pu.t;
          pulsePos[i * 3 + 1] = A.y + (B.y - A.y) * pu.t;
          pulsePos[i * 3 + 2] = A.z + (B.z - A.z) * pu.t;
        }
        pulseGeo.attributes.position.needsUpdate = true;
        renderer.render(scene, camera);
      };
      animate();

      const ro = new ResizeObserver(() => {
        const w = mount.clientWidth, h = mount.clientHeight;
        if (!w || !h) return;
        camera.aspect = w / h; camera.updateProjectionMatrix();
        renderer.setSize(w, h);
      });
      ro.observe(mount);

      cleanup = () => {
        cancelAnimationFrame(raf);
        ro.disconnect();
        window.removeEventListener('pointermove', onMove);
        window.removeEventListener('scroll', onScroll);
        geo.dispose(); mat.dispose();
        somaGeo.dispose(); somaMat.dispose();
        elgeo.dispose(); elmat.dispose();
        pulseGeo.dispose(); pulseMat.dispose();
        coreGeo.dispose(); coreMat.dispose();
        renderer.dispose();
        if (renderer.domElement.parentNode === mount) mount.removeChild(renderer.domElement);
      };
    })();

    return () => { disposed = true; cleanup(); };
  }, []);

  return (
    // Tall spacer pins the canvas: as it scrolls through, `progress` dollies the
    // camera into the brain and fades the canvas out, revealing the dashboard.
    <div ref={wrapRef} className="relative" style={{ height: staticHero ? '100vh' : '185vh' }}>
      <div className="sticky top-0 h-screen overflow-hidden">
        <div ref={mountRef} className="absolute inset-0" />
        <div className="absolute inset-0 pointer-events-none bg-[radial-gradient(ellipse_at_center,rgba(79,70,229,0.14),transparent_60%)]" />
        {staticHero && (
          // CSS-only fallback if WebGL / the CDN is unavailable — never blank.
          <div className="absolute inset-0 pointer-events-none bg-[radial-gradient(circle_at_50%_42%,rgba(251,113,133,0.2),rgba(79,70,229,0.16)_42%,transparent_72%)]" />
        )}
        <div
          ref={copyRef}
          className="relative z-10 h-full flex flex-col items-center justify-center text-center px-6 pointer-events-none"
        >
          <div className="mb-5 text-[11px] sm:text-xs font-semibold uppercase tracking-[0.3em] text-indigo-300/80">
            Adversarial Agent Reliability
          </div>
          <h1 className="text-5xl sm:text-6xl md:text-7xl font-black tracking-tight leading-[1.05]">
            <span className="bg-clip-text text-transparent bg-gradient-to-r from-rose-400 via-fuchsia-400 to-indigo-400">
              Break your agent<br className="hidden sm:block" /> before your users do.
            </span>
          </h1>
          <p className="mt-6 max-w-xl text-slate-300/90 text-base sm:text-lg leading-relaxed">
            AgentCI stress-tests AI agents against prompt injection, destructive tool calls, and
            data-leak traps — so failures surface here, not in production.
          </p>
          <button
            onClick={scrollToApp}
            className="pointer-events-auto mt-9 px-6 py-3 rounded-xl font-semibold text-white bg-gradient-to-r from-rose-500 to-indigo-500 hover:from-rose-400 hover:to-indigo-400 transition-all shadow-lg shadow-indigo-500/25 hover:shadow-indigo-500/40 hover:-translate-y-0.5"
          >
            Enter the console
          </button>
        </div>
        <button
          onClick={scrollToApp}
          className="absolute bottom-6 left-1/2 -translate-x-1/2 z-10 flex flex-col items-center gap-1 text-slate-400 hover:text-indigo-300 transition-colors"
          aria-label="Scroll to console"
        >
          <span className="text-[11px] uppercase tracking-widest">scroll through</span>
          <ChevronDown className="w-5 h-5 animate-bounce" />
        </button>
      </div>
    </div>
  );
}
