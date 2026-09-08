/**
 * <alembic-viewer> — self-contained web component that plays a baked Alembic
 * geometry sequence (see converter/abc_to_sequence.py) in the browser.
 *
 * Drop-in usage:
 *   <script type="module" src="/path/to/alembic-viewer.js"></script>
 *   <alembic-viewer src="/models/firehorn/manifest.json"></alembic-viewer>
 *
 * No build step, no CDN: three.js + OrbitControls are loaded from ./vendor/
 * relative to THIS file. Keep the vendor/ folder next to alembic-viewer.js.
 *
 * ---------------------------------------------------------------------------
 * ATTRIBUTES  (all also work as JS properties)
 *   src           URL to manifest.json                       (required)
 *   autoplay      boolean attribute — start playing on load
 *   loop          "false"/"0" to disable looping (default: loop)
 *   fps           number — override manifest fps
 *   accent        CSS color for the UI accent   (default #5B9CFF)
 *   background    CSS color for the 3D backdrop (default #16161A)
 *   controls      "full" (default) | "minimal" | "none"
 *   wireframe     "off" (default) | "overlay" | "only"
 *
 * PROPERTIES (read-only)
 *   ready, manifest, frameCount, currentFrame, playing
 *
 * METHODS
 *   play() pause() toggle()
 *   seek(frameIndex)  seekTime(seconds)
 *   setFocalLength(mm)  setWireframe(mode)  resetView()
 *   screenshot({scale=1, type='image/png'}) -> Promise<Blob>
 *   getState() -> {frame, frameCount, playing, fps, focalMm, wireframe}
 *   load(src) -> Promise<void>
 *
 * EVENTS  (CustomEvent, bubbles + composed)
 *   av-ready      {name, frameCount, fps, bbox}
 *   av-frame      {frame, frameCount, time}
 *   av-play  av-pause
 *   av-focal      {mm, fov}
 *   av-wireframe  {mode}
 *   av-error      {message}
 * ---------------------------------------------------------------------------
 */

import * as THREE from './vendor/three.module.js';
import { OrbitControls } from './vendor/OrbitControls.js';

const ICONS = {
  wire: '<path d="M21 8V16a2 2 0 0 1-1 1.73l-7 4a2 2 0 0 1-2 0l-7-4A2 2 0 0 1 3 16V8a2 2 0 0 1 1-1.73l7-4a2 2 0 0 1 2 0l7 4A2 2 0 0 1 21 8z"/><path d="M3.3 7 12 12l8.7-5"/><path d="M12 22V12"/>',
  fit: '<path d="M3 7V5a2 2 0 0 1 2-2h2"/><path d="M17 3h2a2 2 0 0 1 2 2v2"/><path d="M21 17v2a2 2 0 0 1-2 2h-2"/><path d="M7 21H5a2 2 0 0 1-2-2v-2"/><circle cx="12" cy="12" r="3"/>',
  shot: '<path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3z"/><circle cx="12" cy="13" r="3"/>',
  full: '<path d="M8 3H5a2 2 0 0 0-2 2v3"/><path d="M21 8V5a2 2 0 0 0-2-2h-3"/><path d="M3 16v3a2 2 0 0 0 2 2h3"/><path d="M16 21h3a2 2 0 0 0 2-2v-3"/>',
  play: '<path d="M8 5v14l11-7z" fill="currentColor" stroke="none"/>',
  pause: '<path d="M7 5h3v14H7zM14 5h3v14h-3z" fill="currentColor" stroke="none"/>',
  loop: '<path d="m17 2 4 4-4 4"/><path d="M3 11v-1a4 4 0 0 1 4-4h14"/><path d="m7 22-4-4 4-4"/><path d="M21 13v1a4 4 0 0 1-4 4H3"/>',
  reset: '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/>',
};
const svg = (p, size = 20) =>
  `<svg viewBox="0 0 24 24" width="${size}" height="${size}" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${p}</svg>`;

const CSS = `
:host{
  --av-accent:#5B9CFF; --av-bg:#16161A;
  --av-panel:rgba(30,30,36,.92); --av-stroke:rgba(255,255,255,.09);
  --av-text:#E7E7EC; --av-text-dim:#9A9AA6;
  position:relative; display:block; width:100%; height:100%; min-height:220px;
  background:var(--av-bg); overflow:hidden; border-radius:inherit;
  font:13px/1.4 system-ui,-apple-system,Segoe UI,Roboto,sans-serif; color:var(--av-text);
  contain:layout paint;
}
canvas{position:absolute; inset:0; display:block; touch-action:none}
.chrome{position:absolute; inset:0; pointer-events:none}
.chrome > *{pointer-events:auto}

.panel{
  background:var(--av-panel); border:1px solid var(--av-stroke); border-radius:14px;
  -webkit-backdrop-filter:blur(10px); backdrop-filter:blur(10px);
  box-shadow:0 12px 32px -8px rgba(0,0,0,.45);
}
.hud{
  position:absolute; left:16px; top:16px; display:flex; gap:9px; align-items:center;
  padding:8px 13px; border-radius:999px; background:rgba(20,20,24,.72);
  border:1px solid var(--av-stroke); white-space:nowrap;
}
.hud b{font-weight:500}
.hud span{color:var(--av-text-dim)}
.hud i{width:3px;height:3px;border-radius:50%;background:var(--av-text-dim);opacity:.55;display:inline-block}

.toolbar{position:absolute; right:16px; top:16px; display:flex; gap:4px; padding:6px;
  border-radius:12px; background:rgba(20,20,24,.72); border:1px solid var(--av-stroke)}
.iconbtn{width:36px;height:36px;display:grid;place-items:center;border:0;border-radius:8px;
  background:transparent;color:#C9C9D2;cursor:pointer;transition:background .12s}
.iconbtn:hover{background:rgba(255,255,255,.07)}
.iconbtn[aria-pressed="true"]{background:rgba(91,156,255,.22);color:#fff}
.playbtn span{display:flex}
.playbtn .i-pause{display:none}
.playbtn[data-playing] .i-play{display:none}
.playbtn[data-playing] .i-pause{display:flex}

.lens{position:absolute; right:16px; top:74px; width:262px; padding:16px 18px;
  display:flex; flex-direction:column; gap:13px}
.lens .ttl{font-weight:600;font-size:11px;letter-spacing:.4px;color:var(--av-text-dim);text-transform:uppercase}
.lens .val{display:flex; align-items:baseline; gap:6px}
.lens .val b{font-size:33px;font-weight:600;letter-spacing:-.5px}
.lens .val span{font-size:15px;color:var(--av-text-dim)}
.lens .rng{display:flex;justify-content:space-between;font-size:11px;color:var(--av-text-dim);margin-top:-6px}
.lens .presets{display:flex;gap:6px}
.lens .presets button{flex:1;padding:6px 0;border:0;border-radius:8px;background:rgba(255,255,255,.05);
  color:var(--av-text);font:inherit;font-size:11px;cursor:pointer}
.lens .presets button[data-active]{background:var(--av-accent);color:#08101f;font-weight:500}
.lens .divider{height:1px;background:rgba(255,255,255,.07)}
.btn{display:flex;align-items:center;justify-content:center;gap:7px;padding:9px;border-radius:9px;
  background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.08);color:var(--av-text);
  font:inherit;font-size:12px;font-weight:500;cursor:pointer}
.btn:hover{background:rgba(255,255,255,.1)}

.transport{position:absolute; left:16px; right:16px; bottom:16px; display:flex; align-items:center;
  gap:16px; padding:12px 16px}
.playbtn{width:40px;height:40px;flex:none;border:0;border-radius:999px;background:var(--av-accent);
  color:#08101f;display:grid;place-items:center;cursor:pointer}
.scrub{flex:1;min-width:60px}
.count{font-variant-numeric:tabular-nums;white-space:nowrap}
.count b{font-weight:500}
.count span{color:var(--av-text-dim)}
.time{color:var(--av-text-dim);font-variant-numeric:tabular-nums}
.rule{width:1px;height:22px;background:rgba(255,255,255,.09)}
.fps{display:flex;align-items:center;gap:6px;padding:6px 10px;border-radius:8px;background:rgba(255,255,255,.05);cursor:pointer}
.fps b{font-weight:500}.fps span{color:var(--av-text-dim);font-size:11px}

input[type=range]{-webkit-appearance:none;appearance:none;width:100%;height:16px;background:transparent;cursor:pointer;margin:0}
input[type=range]::-webkit-slider-runnable-track{height:4px;border-radius:2px;
  background:linear-gradient(var(--av-accent),var(--av-accent)) 0/var(--_p,0%) 100% no-repeat, rgba(255,255,255,.14)}
input[type=range]::-moz-range-track{height:4px;border-radius:2px;background:rgba(255,255,255,.14)}
input[type=range]::-moz-range-progress{height:4px;border-radius:2px;background:var(--av-accent)}
input[type=range]::-webkit-slider-thumb{-webkit-appearance:none;appearance:none;width:14px;height:14px;
  margin-top:-5px;border-radius:50%;background:#fff;box-shadow:0 0 0 3px rgba(91,156,255,.5),0 2px 6px rgba(0,0,0,.4)}
input[type=range]::-moz-range-thumb{width:14px;height:14px;border:0;border-radius:50%;background:#fff;
  box-shadow:0 0 0 3px rgba(91,156,255,.5),0 2px 6px rgba(0,0,0,.4)}

.overlay-msg{position:absolute;left:16px;bottom:16px;padding:8px 12px;border-radius:8px;
  background:rgba(0,0,0,.6);color:var(--av-text-dim)}
.overlay-msg.err{color:#ff9090}

:host([controls="none"]) .chrome{display:none}
:host([controls="minimal"]) .toolbar,
:host([controls="minimal"]) .lens{display:none}
:host(.av-compact) .lens{display:none}
:host(.av-compact) .hud{font-size:12px}
:host(.av-compact) .time,:host(.av-compact) .rule,:host(.av-compact) .fps{display:none}
`;

class AlembicViewer extends HTMLElement {
  static get observedAttributes() { return ['src', 'accent', 'background', 'controls', 'wireframe']; }

  constructor() {
    super();
    this._sr = this.attachShadow({ mode: 'open' });
    this._state = {
      ready: false, playing: false, frame: 0, fps: 24, loop: true,
      focalMm: 50, wire: 'off',
    };
    this._geoms = [];
    this._manifest = null;
    this._maxDiag = 1e-4;
    this._acc = 0;
    this._raf = 0;
  }

  /* ---------------- lifecycle ---------------- */
  connectedCallback() {
    if (this.hasAttribute('loop')) {
      const v = this.getAttribute('loop');
      this._state.loop = !(v === 'false' || v === '0');
    }
    if (this.hasAttribute('fps')) this._state.fps = +this.getAttribute('fps') || 24;
    this._state.wire = this.getAttribute('wireframe') || 'off';

    this._build();
    this._initThree();
    this._observer = new ResizeObserver(() => this._resize());
    this._observer.observe(this);
    this._tick = this._tick.bind(this);
    this._raf = requestAnimationFrame(this._tick);

    const src = this.getAttribute('src');
    if (src) this.load(src);
  }

  disconnectedCallback() {
    cancelAnimationFrame(this._raf);
    this._observer?.disconnect();
    this._renderer?.dispose();
    this._geoms.forEach((g) => g.dispose());
    this._geoms = [];
  }

  attributeChangedCallback(name, oldV, newV) {
    if (oldV === newV) return;
    if (name === 'src' && newV && this._renderer) this.load(newV);
    if (name === 'accent') this.style.setProperty('--av-accent', newV || '#5B9CFF');
    if (name === 'background') {
      this.style.setProperty('--av-bg', newV || '#16161A');
      if (this._scene) this._scene.background = new THREE.Color(newV || '#16161A');
    }
    if (name === 'wireframe') this.setWireframe(newV || 'off');
  }

  /* ---------------- public API ---------------- */
  get ready() { return this._state.ready; }
  get manifest() { return this._manifest; }
  get frameCount() { return this._geoms.length; }
  get currentFrame() { return this._state.frame; }
  get playing() { return this._state.playing; }

  play() { if (this._geoms.length > 1) { this._state.playing = true; this._syncUI(); this._emit('av-play'); } }
  pause() { this._state.playing = false; this._syncUI(); this._emit('av-pause'); }
  toggle() { this._state.playing ? this.pause() : this.play(); }

  seek(i) { this.pause(); this._setFrame(i); }
  seekTime(sec) { this.seek(Math.round(sec * this._state.fps)); }

  setFocalLength(mm) {
    mm = Math.max(1, +mm || 50);
    this._state.focalMm = mm;
    this._camera.setFocalLength(mm);
    this._camera.updateProjectionMatrix();
    this._syncUI();
    this._emit('av-focal', { mm, fov: +this._camera.fov.toFixed(2) });
  }

  setWireframe(mode) {
    if (!['off', 'overlay', 'only'].includes(mode)) mode = 'off';
    this._state.wire = mode;
    for (const m of this._matList()) m.wireframe = mode === 'only';
    if (this._overlay) {
      this._overlay.visible = mode === 'overlay';
      if (mode === 'overlay' && this._geoms.length) this._rebuildOverlay();
    }
    this._syncUI();
    this._emit('av-wireframe', { mode });
  }

  resetView() { this._frameView(); }

  _matList() { return this._materials || [this._defaultMat]; }

  async screenshot({ scale = 1, type = 'image/png' } = {}) {
    this._renderer.render(this._scene, this._camera);
    const src = this._renderer.domElement;
    if (scale === 1) return await new Promise((res) => src.toBlob(res, type));
    const c = document.createElement('canvas');
    c.width = src.width * scale; c.height = src.height * scale;
    c.getContext('2d').drawImage(src, 0, 0, c.width, c.height);
    return await new Promise((res) => c.toBlob(res, type));
  }

  getState() {
    return {
      frame: this._state.frame, frameCount: this._geoms.length,
      playing: this._state.playing, fps: this._state.fps,
      focalMm: this._state.focalMm, wireframe: this._state.wire,
    };
  }

  async load(src) {
    this._state.ready = false;
    this._msg('chargement…');
    try {
      const manifest = await fetch(src, { cache: 'no-store' }).then((r) => {
        if (!r.ok) throw new Error(`manifest ${r.status}`);
        return r.json();
      });
      const base = src.slice(0, src.lastIndexOf('/'));
      const geoms = [];
      for (let i = 0; i < manifest.frames.length; i++) {
        const fm = manifest.frames[i];
        const buf = await fetch(`${base}/${fm.file}`, { cache: 'no-store' }).then((r) => {
          if (!r.ok) throw new Error(`${fm.file} ${r.status}`);
          return r.arrayBuffer();
        });
        geoms.push(buildGeometry(buf, fm));
        this._msg(`chargement ${i + 1}/${manifest.frames.length}…`);
      }

      this._geoms.forEach((g) => g.dispose());
      this._geoms = geoms;
      this._manifest = manifest;
      if (!this.hasAttribute('fps')) this._state.fps = manifest.fps || 24;

      // materials from the manifest (flat PBR); fall back to the neutral grey
      this._materials?.forEach((m) => m.dispose());
      if (Array.isArray(manifest.materials) && manifest.materials.length) {
        this._materials = manifest.materials.map(toFlatMat);
        this._mesh.material = this._materials.length > 1 ? this._materials : this._materials[0];
      } else {
        this._materials = null;
        this._mesh.material = this._defaultMat;
      }

      const v = new THREE.Vector3();
      this._maxDiag = 1e-4;
      for (const g of geoms) { g.computeBoundingBox(); this._maxDiag = Math.max(this._maxDiag, g.boundingBox.getSize(v).length()); }

      this._state.frame = 0;
      this._setFrame(0);
      this._frameView();
      this.setWireframe(this._state.wire);
      this._state.ready = true;
      this._msg('');
      this._buildScrub();
      this._syncUI();
      this._emit('av-ready', {
        name: manifest.name, frameCount: geoms.length,
        fps: this._state.fps, bbox: manifest.bbox,
      });
      if (this.hasAttribute('autoplay')) this.play();
    } catch (e) {
      this._msg(`Erreur : ${e.message}`, true);
      this._emit('av-error', { message: e.message });
    }
  }

  /* ---------------- three.js ---------------- */
  _initThree() {
    const canvas = this._sr.querySelector('canvas');
    this._renderer = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: true });
    this._renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    this._renderer.toneMapping = THREE.ACESFilmicToneMapping;

    this._scene = new THREE.Scene();
    this._scene.background = new THREE.Color(this.getAttribute('background') || '#16161A');

    this._camera = new THREE.PerspectiveCamera(45, 1, 0.01, 1000);
    this._camera.filmGauge = 36;

    this._controls = new OrbitControls(this._camera, this._renderer.domElement);
    this._controls.enableDamping = true;
    this._controls.dampingFactor = 0.08;

    this._scene.add(
      new THREE.HemisphereLight(0xffffff, 0x35353f, 0.55),
      dir(0xffffff, 1.15, 3, 5, 4),
      dir(0xffffff, 0.35, -4, 2, -3),
      dir(0xffffff, 0.6, 0, 3, -5),
    );

    this._defaultMat = new THREE.MeshStandardMaterial({ color: 0xc9ccd4, roughness: 0.62, metalness: 0 });
    this._materials = null; // set from manifest.materials in load()
    this._mesh = new THREE.Mesh(new THREE.BufferGeometry(), this._defaultMat);
    this._scene.add(this._mesh);

    this._overlay = new THREE.LineSegments(
      new THREE.BufferGeometry(),
      new THREE.LineBasicMaterial({ color: 0x0a0a0a, transparent: true, opacity: 0.3 }),
    );
    this._overlay.visible = false;
    this._mesh.add(this._overlay);

    this._resize();
  }

  _resize() {
    const w = this.clientWidth || 1, h = this.clientHeight || 1;
    this._renderer.setSize(w, h, false);
    this._camera.aspect = w / h;
    this._camera.setFocalLength(this._state.focalMm);
    this._camera.updateProjectionMatrix();
    this.classList.toggle('av-compact', w < 520);
  }

  _frameCenter(i, out) {
    const g = this._geoms[i];
    if (!g.boundingBox) g.computeBoundingBox();
    return out.addVectors(g.boundingBox.min, g.boundingBox.max).multiplyScalar(0.5);
  }

  _setFrame(i) {
    if (!this._geoms.length) return;
    const n = Math.max(0, Math.min(i | 0, this._geoms.length - 1));
    this._state.frame = n;
    this._mesh.geometry = this._geoms[n];
    if (this._state.wire === 'overlay') this._rebuildOverlay();
    // NB: no per-frame re-centering — the model animates freely in the view.
    // Use resetView() / the "recadrer" button to re-frame on demand.
    this._syncFrame();
    this._emit('av-frame', { frame: n, frameCount: this._geoms.length, time: n / this._state.fps });
  }

  _rebuildOverlay() {
    this._overlay.geometry.dispose();
    this._overlay.geometry = new THREE.WireframeGeometry(this._geoms[this._state.frame]);
  }

  _frameView() {
    if (!this._geoms.length) return;
    const c = this._frameCenter(this._state.frame, new THREE.Vector3());
    const radius = Math.max(0.5 * this._maxDiag, 1e-4);
    this._camera.setFocalLength(this._state.focalMm);
    this._camera.updateProjectionMatrix();
    const vFit = radius / Math.tan(THREE.MathUtils.degToRad(this._camera.fov * 0.5));
    const hFit = vFit / Math.min(this._camera.aspect, 1);
    const dist = 1.25 * Math.max(vFit, hFit);
    this._controls.target.copy(c);
    this._camera.position.copy(c).addScaledVector(new THREE.Vector3(0.6, 0.4, 1).normalize(), dist);
    this._camera.near = Math.max(dist / 1000, radius / 1000);
    this._camera.far = dist + radius * 20;
    this._camera.updateProjectionMatrix();
    this._controls.update();
  }

  _tick(t) {
    this._raf = requestAnimationFrame(this._tick);
    const dt = this._clock ? this._clock.getDelta() : 0;
    if (!this._clock) this._clock = new THREE.Clock();
    if (this._state.playing && this._geoms.length > 1) {
      this._acc += dt;
      const spf = 1 / this._state.fps;
      let adv = false;
      while (this._acc >= spf) {
        this._acc -= spf;
        let n = this._state.frame + 1;
        if (n >= this._geoms.length) {
          if (this._state.loop) n = 0;
          else { n = this._geoms.length - 1; this._state.playing = false; this._emit('av-pause'); }
        }
        this._state.frame = n; adv = true;
      }
      if (adv) this._setFrame(this._state.frame);
    }
    this._controls?.update();
    this._renderer?.render(this._scene, this._camera);
  }

  /* ---------------- UI ---------------- */
  _build() {
    this._sr.innerHTML = `
      <style>${CSS}</style>
      <canvas></canvas>
      <div class="chrome">
        <div class="hud panel">
          <b data-name>—</b><i></i>
          <span data-frame>frame 0 / 0</span><i></i>
          <span data-focal>50 mm</span><span data-wire></span>
        </div>
        <div class="toolbar">
          <button class="iconbtn" data-act="wire"   title="Wireframe (W)">${svg(ICONS.wire)}</button>
          <button class="iconbtn" data-act="fit"    title="Recadrer (F)">${svg(ICONS.fit)}</button>
          <button class="iconbtn" data-act="shot"   title="Screenshot">${svg(ICONS.shot)}</button>
          <button class="iconbtn" data-act="full"   title="Plein écran">${svg(ICONS.full)}</button>
        </div>
        <div class="lens panel">
          <div class="ttl">Lens</div>
          <div class="val"><b data-fval>50</b><span>mm</span></div>
          <input type="range" data-focal-range min="12" max="120" step="1" value="50">
          <div class="rng"><span>12</span><span>120</span></div>
          <div class="presets">
            ${[18, 24, 35, 50, 85].map((v) => `<button data-preset="${v}">${v}</button>`).join('')}
          </div>
          <div class="divider"></div>
          <button class="btn" data-act="fit">${svg(ICONS.reset, 14)} Reset view</button>
        </div>
        <div class="transport panel">
          <button class="playbtn" data-act="toggle" title="Play / Pause (Espace)"><span class="i-play">${svg(ICONS.play, 18)}</span><span class="i-pause">${svg(ICONS.pause, 18)}</span></button>
          <input class="scrub" type="range" data-scrub min="0" max="0" step="1" value="0">
          <div class="count"><b data-cur>0</b> <span data-total>/ 0</span></div>
          <div class="time" data-time>00:00:00</div>
          <div class="rule"></div>
          <div class="fps" data-act="fpsdown" title="FPS"><b data-fps>24</b><span>fps</span></div>
          <button class="iconbtn" data-act="loop" aria-pressed="true" title="Loop">${svg(ICONS.loop, 18)}</button>
        </div>
        <div class="overlay-msg" data-msg hidden></div>
      </div>`;

    this._sr.addEventListener('click', (e) => {
      const el = e.target.closest('[data-act],[data-preset]');
      if (!el) return;
      if (el.dataset.preset) return this.setFocalLength(+el.dataset.preset);
      switch (el.dataset.act) {
        case 'toggle': return this.toggle();
        case 'wire': return this.setWireframe(this._state.wire === 'off' ? 'overlay' : 'off');
        case 'fit': return this.resetView();
        case 'shot': return this._download();
        case 'full': return this._toggleFull();
        case 'loop':
          this._state.loop = !this._state.loop;
          el.setAttribute('aria-pressed', String(this._state.loop));
          return;
        case 'fpsdown': {
          const opts = [12, 15, 24, 25, 30, 48, 50, 60];
          const i = opts.indexOf(this._state.fps);
          this._state.fps = opts[(i + 1) % opts.length];
          return this._syncUI();
        }
      }
    });
    this._sr.querySelector('[data-focal-range]').addEventListener('input', (e) => this.setFocalLength(+e.target.value));
    this._sr.querySelector('[data-scrub]').addEventListener('input', (e) => this.seek(+e.target.value));

    this.tabIndex = this.tabIndex < 0 ? 0 : this.tabIndex;
    this.addEventListener('keydown', (e) => {
      if (e.code === 'Space') { e.preventDefault(); this.toggle(); }
      else if (e.code === 'ArrowRight') this.seek(this._state.frame + 1);
      else if (e.code === 'ArrowLeft') this.seek(this._state.frame - 1);
      else if (e.key.toLowerCase() === 'w') this.setWireframe(this._state.wire === 'off' ? 'overlay' : 'off');
      else if (e.key.toLowerCase() === 'f') this.resetView();
    });
  }

  _buildScrub() {
    const s = this._sr.querySelector('[data-scrub]');
    s.max = String(Math.max(0, this._geoms.length - 1));
  }

  // cheap, safe to call every frame — never rebuilds a clickable control
  _syncFrame() {
    const $ = (q) => this._sr.querySelector(q);
    const st = this._state, n = this._geoms.length;
    $('[data-frame]').textContent = `frame ${st.frame + 1} / ${n || 0}`;
    const sc = $('[data-scrub]'); sc.value = String(st.frame);
    sc.style.setProperty('--_p', `${n > 1 ? (st.frame / (n - 1)) * 100 : 0}%`);
    $('[data-cur]').textContent = String(st.frame + 1);
    $('[data-total]').textContent = `/ ${n || 0}`;
    $('[data-time]').textContent = fmtTime(st.frame / st.fps);
  }

  // full sync — only on discrete state changes (load / play / pause / focal / wire / fps / resize)
  _syncUI() {
    this._syncFrame();
    const $ = (q) => this._sr.querySelector(q);
    const st = this._state;
    $('[data-name]').textContent = this._manifest?.name || '—';
    $('[data-focal]').textContent = `${st.focalMm} mm · ${this._camera.fov.toFixed(1)}°`;
    $('[data-wire]').textContent = st.wire === 'off' ? '' : ` · wireframe ${st.wire}`;
    $('[data-fval]').textContent = String(st.focalMm);
    const fr = $('[data-focal-range]');
    fr.value = String(st.focalMm);
    fr.style.setProperty('--_p', `${((st.focalMm - +fr.min) / (+fr.max - +fr.min)) * 100}%`);
    $('[data-fps]').textContent = String(st.fps);
    $('[data-act="toggle"]').toggleAttribute('data-playing', st.playing);
    for (const b of this._sr.querySelectorAll('[data-preset]'))
      b.toggleAttribute('data-active', +b.dataset.preset === st.focalMm);
    this._sr.querySelector('[data-act="wire"]').setAttribute('aria-pressed', String(st.wire !== 'off'));
  }

  _msg(text, err = false) {
    const el = this._sr.querySelector('[data-msg]');
    el.hidden = !text; el.textContent = text; el.classList.toggle('err', err);
  }

  async _download() {
    const blob = await this.screenshot();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `${this._manifest?.name || 'frame'}_${String(this._state.frame).padStart(4, '0')}.png`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  _toggleFull() {
    if (document.fullscreenElement) document.exitFullscreen();
    else this.requestFullscreen?.();
  }

  _emit(type, detail) {
    this.dispatchEvent(new CustomEvent(type, { detail, bubbles: true, composed: true }));
  }
}

/* ---------------- helpers ---------------- */
function dir(color, intensity, x, y, z) {
  const l = new THREE.DirectionalLight(color, intensity);
  l.position.set(x, y, z);
  return l;
}

// manifest material entry -> FLAT (unlit) material. .chou / USD materials are
// deliberately flat: a base colour (or, later, a base-colour texture), no PBR.
// baseColor is linear (from Blender).
function toFlatMat(m) {
  const bc = m.baseColor || [0.8, 0.8, 0.8, 1];
  const col = new THREE.Color();
  if (col.setRGB.length >= 4) col.setRGB(bc[0], bc[1], bc[2], THREE.LinearSRGBColorSpace);
  else col.setRGB(bc[0], bc[1], bc[2]);
  const mat = new THREE.MeshBasicMaterial({ color: col });
  if (bc[3] != null && bc[3] < 1) { mat.transparent = true; mat.opacity = bc[3]; }
  mat.name = m.name || '';
  return mat;
}

function buildGeometry(buf, fm) {
  const v = fm.vertexCount | 0, t = fm.triangleCount | 0;
  let o = 0;
  const position = new Float32Array(buf, o, v * 3); o += v * 12;
  const normal = new Float32Array(buf, o, v * 3); o += v * 12;
  const index = new Uint32Array(buf, o, t * 3);
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(position, 3));
  g.setAttribute('normal', new THREE.BufferAttribute(normal, 3));
  g.setIndex(new THREE.BufferAttribute(index, 1));
  // per-material face groups: [indexStart, indexCount, materialIndex]
  if (Array.isArray(fm.groups) && fm.groups.length) {
    for (const [start, count, mi] of fm.groups) g.addGroup(start, count, mi);
  }
  g.computeBoundingSphere();
  return g;
}

function fmtTime(sec) {
  sec = Math.max(0, sec);
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  const f = Math.floor((sec % 1) * 100);
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}:${String(f).padStart(2, '0')}`;
}

customElements.define('alembic-viewer', AlembicViewer);
export { AlembicViewer };
