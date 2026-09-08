// alembic-viewer in React
// ------------------------
// The component is a native custom element, so React just renders the tag.
// Import the module once (side-effect import registers <alembic-viewer>).
//
//   npm/pnpm: copy alembic-viewer.js + vendor/ into your /public and load it,
//   or serve them from any static path. There is no npm package — it's a
//   dependency-free ES module.

import { useEffect, useRef, useState } from 'react';

// side-effect import — adjust the path to wherever you serve the file
import '/vendor/alembic-viewer/alembic-viewer.js';

export function AlembicPreview({ src, accent = '#5B9CFF' }) {
  const ref = useRef(null);
  const [frame, setFrame] = useState(0);
  const [total, setTotal] = useState(0);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const onReady = (e) => setTotal(e.detail.frameCount);
    const onFrame = (e) => setFrame(e.detail.frame);
    el.addEventListener('av-ready', onReady);
    el.addEventListener('av-frame', onFrame);
    return () => {
      el.removeEventListener('av-ready', onReady);
      el.removeEventListener('av-frame', onFrame);
    };
  }, []);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={{ height: 420, borderRadius: 12, overflow: 'hidden' }}>
        {/* React 19+ passes unknown props straight through as attributes.
            On React <=18, set attributes via the ref instead (see note below). */}
        <alembic-viewer ref={ref} src={src} accent={accent} autoplay loop
                        style={{ width: '100%', height: '100%' }} />
      </div>

      <div style={{ display: 'flex', gap: 8 }}>
        <button onClick={() => ref.current.toggle()}>play / pause</button>
        <button onClick={() => ref.current.setFocalLength(35)}>35 mm</button>
        <button onClick={() => ref.current.setWireframe('overlay')}>wireframe</button>
        <button onClick={async () => {
          const blob = await ref.current.screenshot({ scale: 2 });
          window.open(URL.createObjectURL(blob));
        }}>screenshot</button>
        <span>{frame + 1} / {total}</span>
      </div>
    </div>
  );
}

/*
 * React <= 18 note
 * ----------------
 * Older React serializes camelCase props and does not forward arbitrary
 * attributes to custom elements. Set them imperatively:
 *
 *   useEffect(() => {
 *     const el = ref.current;
 *     el.setAttribute('src', src);
 *     el.setAttribute('accent', accent);
 *     el.toggleAttribute('autoplay', true);
 *   }, [src, accent]);
 *
 * and render just <alembic-viewer ref={ref} />.
 */
