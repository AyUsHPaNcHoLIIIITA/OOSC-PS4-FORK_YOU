import { useEffect, useRef, useState } from 'react';
import { ChevronDown, BrainCircuit } from 'lucide-react';

// three.js is loaded at runtime from a pinned CDN (see three-cdn.d.ts) so nothing
// is added to package.json or the bundle — same pattern as PipelineView3D. If the
// CDN or WebGL is unavailable the hero degrades to a CSS-only glow so the landing
// page never renders blank.
const THREE_URL = 'https://esm.sh/three@0.171.0';

function scrollToApp() {
  document.getElementById('app-start')?.scrollIntoView({ behavior: 'smooth' });
}

export default function BrainHero() {
  const mountRef = useRef<HTMLDivElement | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
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

      const width = mount.clientWidth;
      const height = mount.clientHeight;

      const scene = new THREE.Scene();
      scene.fog = new THREE.FogExp2(0x0b1020, 0.14);

      const camera = new THREE.PerspectiveCamera(50, width / height, 0.1, 100);
      camera.position.set(0, 0.2, 3.5);

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

      const cLow = new THREE.Color('#6366f1');   // indigo base
      const cHigh = new THREE.Color('#f43f5e');  // rose crown
      const cFire = new THREE.Color('#22d3ee');  // cyan active synapse

      // layered sinusoids ≈ cortical folds (gyri / sulci)
      const fold = (theta: number, phi: number) =>
        1
        + 0.11 * Math.sin(7 * theta) * Math.sin(6 * phi)
        + 0.07 * Math.sin(13 * phi + 2 * theta)
        + 0.05 * Math.sin(11 * theta) * Math.cos(9 * phi);

      const sample = (): [number, number, number] => {
        const u = Math.random();
        const v = Math.random();
        const theta = 2 * Math.PI * u;
        const phi = Math.acos(2 * v - 1);
        const r = fold(theta, phi);
        let x = r * Math.sin(phi) * Math.cos(theta);
        let y = r * Math.cos(phi);
        const z = r * Math.sin(phi) * Math.sin(theta);
        // longitudinal fissure: push each side off the midline to open a groove
        x = Math.sign(x || 1) * (Math.abs(x) * 0.62 + 0.12);
        if (y < 0) y *= 0.8; // flatten the underside
        // ellipsoid proportions: long front-back (z), tall (y), narrow (x)
        return [x * 1.15, y * 1.12, z * 1.55];
      };

      const COUNT = 15000;
      const CEREB = 2200;
      const TOTAL = COUNT + CEREB;
      const positions = new Float32Array(TOTAL * 3);
      const colors = new Float32Array(TOTAL * 3);
      const tmp = new THREE.Color();

      // cerebrum
      for (let i = 0; i < COUNT; i++) {
        const [x, y, z] = sample();
        positions[i * 3] = x;
        positions[i * 3 + 1] = y;
        positions[i * 3 + 2] = z;
        const h = THREE.MathUtils.clamp((y + 1.2) / 2.4, 0, 1);
        tmp.copy(cLow).lerp(cHigh, h);
        if (Math.random() < 0.06) tmp.copy(cFire); // scattered active neurons
        colors[i * 3] = tmp.r; colors[i * 3 + 1] = tmp.g; colors[i * 3 + 2] = tmp.b;
      }
      // cerebellum: smaller, denser, tightly folded cluster at the back-underside
      for (let i = COUNT; i < TOTAL; i++) {
        const u = Math.random(); const v = Math.random();
        const theta = 2 * Math.PI * u; const phi = Math.acos(2 * v - 1);
        const r = 0.5 * (1 + 0.18 * Math.sin(16 * phi) + 0.12 * Math.sin(14 * theta));
        const x = r * Math.sin(phi) * Math.cos(theta) * 1.1;
        const y = r * Math.cos(phi) * 0.7 - 0.72;
        const z = r * Math.sin(phi) * Math.sin(theta) * 0.9 - 1.05;
        positions[i * 3] = x; positions[i * 3 + 1] = y; positions[i * 3 + 2] = z;
        tmp.copy(cLow).lerp(cFire, 0.25 + Math.random() * 0.2);
        colors[i * 3] = tmp.r; colors[i * 3 + 1] = tmp.g; colors[i * 3 + 2] = tmp.b;
      }

      const geo = new THREE.BufferGeometry();
      geo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
      geo.setAttribute('color', new THREE.BufferAttribute(colors, 3));
      const mat = new THREE.PointsMaterial({
        size: 0.022, vertexColors: true, transparent: true, opacity: 0.9,
        blending: THREE.AdditiveBlending, depthWrite: false,
      });
      const points = new THREE.Points(geo, mat);
      group.add(points);

      // faint synaptic links between nearby points — reads as neurons wiring up
      const LINKS = 750;
      const lp = new Float32Array(LINKS * 6);
      for (let i = 0; i < LINKS; i++) {
        const a = Math.floor(Math.random() * COUNT);
        const ax = positions[a * 3], ay = positions[a * 3 + 1], az = positions[a * 3 + 2];
        let b = a;
        for (let t = 0; t < 8; t++) {
          const cand = Math.floor(Math.random() * COUNT);
          const dx = positions[cand * 3] - ax;
          const dy = positions[cand * 3 + 1] - ay;
          const dz = positions[cand * 3 + 2] - az;
          if (dx * dx + dy * dy + dz * dz < 0.08) { b = cand; break; }
        }
        lp[i * 6] = ax; lp[i * 6 + 1] = ay; lp[i * 6 + 2] = az;
        lp[i * 6 + 3] = positions[b * 3];
        lp[i * 6 + 4] = positions[b * 3 + 1];
        lp[i * 6 + 5] = positions[b * 3 + 2];
      }
      const lgeo = new THREE.BufferGeometry();
      lgeo.setAttribute('position', new THREE.BufferAttribute(lp, 3));
      const lmat = new THREE.LineBasicMaterial({
        color: 0x8b93ff, transparent: true, opacity: 0.12,
        blending: THREE.AdditiveBlending, depthWrite: false,
      });
      const lines = new THREE.LineSegments(lgeo, lmat);
      group.add(lines);

      // soft inner core glow
      const coreGeo = new THREE.SphereGeometry(0.42, 24, 24);
      const coreMat = new THREE.MeshBasicMaterial({
        color: 0x4338ca, transparent: true, opacity: 0.14, blending: THREE.AdditiveBlending,
      });
      group.add(new THREE.Mesh(coreGeo, coreMat));
      group.rotation.y = -0.5;

      // pointer parallax
      let targetRX = 0, targetRY = -0.5;
      const onMove = (ev: PointerEvent) => {
        const rect = renderer.domElement.getBoundingClientRect();
        const nx = ((ev.clientX - rect.left) / rect.width) * 2 - 1;
        const ny = ((ev.clientY - rect.top) / rect.height) * 2 - 1;
        targetRY = -0.5 + nx * 0.5;
        targetRX = ny * 0.28;
      };
      window.addEventListener('pointermove', onMove);

      // stop rendering while the hero is scrolled out of view
      let visible = true;
      const io = new IntersectionObserver(
        (es) => { visible = es[0].isIntersecting; },
        { threshold: 0.02 },
      );
      io.observe(mount);

      const clock = new THREE.Clock();
      let raf = 0;
      const animate = () => {
        raf = requestAnimationFrame(animate);
        if (!visible) return;
        const t = clock.getElapsedTime();
        group.rotation.y += (targetRY - group.rotation.y) * 0.05 + 0.0015;
        group.rotation.x += (targetRX - group.rotation.x) * 0.05;
        group.position.y = Math.sin(t * 0.5) * 0.03;
        mat.opacity = 0.78 + Math.sin(t * 1.6) * 0.12;                    // gentle breathing
        lmat.opacity = 0.08 + (Math.sin(t * 2.1) * 0.5 + 0.5) * 0.12;     // synapses pulse
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

      cleanup = () => {
        cancelAnimationFrame(raf);
        io.disconnect();
        ro.disconnect();
        window.removeEventListener('pointermove', onMove);
        geo.dispose(); mat.dispose();
        lgeo.dispose(); lmat.dispose();
        coreGeo.dispose(); coreMat.dispose();
        renderer.dispose();
        if (renderer.domElement.parentNode === mount) mount.removeChild(renderer.domElement);
      };
    })();

    return () => { disposed = true; cleanup(); };
  }, []);

  return (
    <section
      className="relative left-1/2 -translate-x-1/2 w-screen -mt-6 overflow-hidden"
      style={{ height: 'calc(100vh - 4.25rem)', minHeight: 500 }}
    >
      {/* WebGL brain canvas */}
      <div ref={mountRef} className="absolute inset-0" />

      {/* ambient wash + CSS fallback backdrop (always present) */}
      <div className="absolute inset-0 pointer-events-none bg-[radial-gradient(ellipse_at_center,rgba(99,102,241,0.16),transparent_62%)]" />
      {failed && (
        <div className="absolute inset-0 pointer-events-none bg-[radial-gradient(circle_at_50%_42%,rgba(244,63,94,0.22),rgba(99,102,241,0.16)_42%,transparent_72%)]" />
      )}

      {/* copy overlay */}
      <div className="relative z-10 h-full flex flex-col items-center justify-center text-center px-6 pointer-events-none">
        <div className="inline-flex items-center gap-2 mb-5 px-3 py-1 rounded-full glass-dark text-xs font-medium text-indigo-200 border border-white/10">
          <BrainCircuit className="w-3.5 h-3.5 text-cyan-300" />
          the brain of your agent reliability engine
        </div>
        <h1 className="text-5xl sm:text-6xl md:text-7xl font-black tracking-tight">
          <span className="bg-clip-text text-transparent bg-gradient-to-r from-rose-400 via-fuchsia-400 to-indigo-400">
            Test your agent.
          </span>
        </h1>
        <p className="mt-5 max-w-xl text-slate-300/90 text-base sm:text-lg leading-relaxed">
          Adversarial reliability testing for AI agents — probe prompt injection,
          destructive-action pressure, and data disclosure before they ever act for real.
        </p>
        <button
          onClick={scrollToApp}
          className="pointer-events-auto mt-9 px-6 py-3 rounded-xl font-semibold text-white bg-gradient-to-r from-rose-500 to-indigo-500 hover:from-rose-400 hover:to-indigo-400 transition-all shadow-lg shadow-indigo-500/25 hover:shadow-indigo-500/40 hover:-translate-y-0.5"
        >
          Enter the console
        </button>
      </div>

      {/* scroll cue */}
      <button
        onClick={scrollToApp}
        className="absolute bottom-6 left-1/2 -translate-x-1/2 z-10 flex flex-col items-center gap-1 text-slate-400 hover:text-indigo-300 transition-colors"
        aria-label="Scroll to console"
      >
        <span className="text-[11px] uppercase tracking-widest">scroll</span>
        <ChevronDown className="w-5 h-5 animate-bounce" />
      </button>
    </section>
  );
}
