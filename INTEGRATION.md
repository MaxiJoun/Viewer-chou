# alembic-viewer — guide d'intégration

Lecteur web autonome pour **animations Alembic (`.abc`)** : orbite caméra, focale
réelle (mm), wireframe, timeline. Pensé pour être embarqué dans un outil de
review (clone Kitsu, board type PureRef, page de tâche…).

Deux morceaux **indépendants** :

1. **`converter/abc_to_sequence.py`** — hors-ligne, avec Blender : transforme un
   `.abc` en une séquence binaire + `manifest.json`.
2. **`viewer/alembic-viewer.js`** — un *custom element* `<alembic-viewer>`, sans
   build, sans CDN (three.js est dans `viewer/vendor/`). C'est ce que tu embarques.

Le viewer ne lit **pas** le `.abc` directement (aucun moteur web ne le fait ;
Sketchfab convertit aussi côté serveur). Il lit la sortie du converter.

---

## 1. Format de données (contrat)

Le converter écrit, pour un modèle nommé `NAME` :

```
NAME/
├─ manifest.json
└─ frames/
   ├─ frame_0000.bin
   ├─ frame_0001.bin
   └─ …
```

### manifest.json

```jsonc
{
  "name": "firehorn",
  "source": "firehorn.abc",
  "fps": 24.0,
  "frameStart": 0,
  "frameEnd": 119,
  "frameStep": 1,
  "frameCount": 120,
  "decimate": 1.0,
  "bbox": { "min": [x, y, z], "max": [x, y, z] },   // union de toutes les frames
  "layout": "pos:f32*3N | nrm:f32*3N | idx:u32*3T  (little-endian, world space)",

  // présent si l'entrée portait des matériaux (.chou / USD / .blend) — sinon
  // absent, le viewer met un gris neutre. Matériaux **FLAT / unlit** : une
  // couleur (ou une texture) de base, rien d'autre. baseColor LINÉAIRE RGBA.
  "materials": [
    { "name": "Skin", "baseColor": [0.8, 0.09, 0.8, 1.0] }
  ],

  "frames": [
    {
      "file": "frames/frame_0000.bin", "vertexCount": 8, "triangleCount": 12,
      // groupes de faces par matériau : [indexStart, indexCount, materialIndex]
      "groups": [ [0, 30, 0], [30, 6, 1] ]
    },
    …
  ]
}
```

- `vertexCount` / `triangleCount` sont **par frame** — la topologie peut changer
  d'une frame à l'autre (sims fluide / pyro).
- Géométrie déjà en **espace monde** (le transform de l'objet est baké dedans).
- Les triangles du `.bin` sont **triés par matériau** ; `groups` donne les plages.
  Sans `materials`, `groups` est absent et tout va au matériau par défaut.

### frame_XXXX.bin  (little-endian, sans compression)

Deux layouts selon `manifest.binLayout` :

**`"corners_pos_nrm_uv"`** (scene_to_sequence.py — non-indexé, `N = 3 × triangleCount` coins) :

| bloc      | type      | longueur     |
|-----------|-----------|--------------|
| positions | `float32` | `3 × N`      |
| normals   | `float32` | `3 × N`      |
| uv        | `float32` | `2 × N`      |

```js
const n = fm.vertexCount;            // = 3 * triangleCount
let o = 0;
const position = new Float32Array(buf, o, n * 3); o += n * 12;
const normal   = new Float32Array(buf, o, n * 3); o += n * 12;
const uv       = new Float32Array(buf, o, n * 2);
// pas d'index ; groups = [vertexStart, vertexCount, materialIndex]
```

**Absent** (legacy, abc_to_sequence.py — indexé) : `pos:f32*3V | nrm:f32*3V | idx:u32*3T`,
`groups = [indexStart, indexCount, materialIndex]`.

Dans les deux cas la géométrie est en **espace monde** et triée par matériau.
`baseColorTexture` (chemin relatif, ex. `textures/skin.jpg`) est servi à côté du manifest.

---

## 2. Produire les données

Scripts Blender headless :

| Script | Entrée | Sort |
|---|---|---|
| `abc_to_sequence.py`   | `.abc` | géométrie seule (matériau gris) |
| `scene_to_sequence.py` | `.chou`, `.abc`, `.usd/.usdc/.usda/.usdz`, `.blend` | géométrie **+ matériaux FLAT** (couleur/texture de base) + groupes de faces |
| `export_chou.py`       | (scène Blender) | un `.chou` = `geometry.abc` + `chou.json` (matériaux) — voir [`CHOU_FORMAT.md`](CHOU_FORMAT.md) |

Le **`.chou`** est le fichier de handoff studio : Alembic (l'anim) + le look flat,
zippé. Addon Blender import/export dans `blender_addon/chou_io/`. Le viewer ne lit
jamais le `.chou` — `scene_to_sequence.py` le transforme en séquence web.

```bash
blender --background --factory-startup \
  --python converter/scene_to_sequence.py -- \
  --input  "firehorn.usdc" \
  --outdir "<storage>/previews/<id>" \
  [--decimate 0.5] [--frame-step 1] [--frame-start N] [--frame-end N] [--name NAME]
```

**USD & animation** : Blender **n'importe pas** l'animation UsdSkel /
blendshapes (5.x) — un `.usdc` skinné arrive statique. Pour de l'anim depuis
Blender : sortir en `.abc` (géo, sans matériau) ou, si topo constante, en `.glb`
(anim + matériaux, à brancher séparément). USD reste bon pour un cache de points
non-skinné + matériaux.

| Flag           | Défaut | Effet                                                    |
|----------------|--------|--------------------------------------------------------- |
| `--decimate R` | `1.0`  | ratio `0..1`, décimation par frame — **lever N°1** pour le poids |
| `--frame-step` | `1`    | n'exporte qu'une frame sur N                            |
| `--frame-start`/`--frame-end` | scène | bornes                                  |
| `--name`       | nom du `.abc` | `name` du manifest                              |

À câbler dans le pipeline : au moment où une preview `.abc` est uploadée,
lancer cette commande (Blender headless, worker) et stocker la sortie à côté de
la preview.

### Import interactif (dev / test)

`converter/import_server.py` sert le viewer **et** accepte un `.abc` par
glisser-déposer : il lance Blender, convertit dans `viewer/models/<nom>/`, et la
page recharge le modèle.

```bash
python converter/import_server.py 8080
# POST /import?name=&decimate=&step=   (corps = octets du .abc) -> { name, frameCount }
# GET  /models                        -> ["Untitled", ...]
```

C'est le patron minimal de l'endpoint d'upload à répliquer côté backend Kitsu :
recevoir le fichier → `subprocess` Blender → exposer `manifest.json` + `frames/`.

---

## 3. Embarquer — Option A : web component (recommandé)

Framework-agnostic, styles isolés (Shadow DOM), pas d'iframe.

```html
<script type="module" src="/assets/alembic-viewer/alembic-viewer.js"></script>

<alembic-viewer
  src="/api/previews/1234/manifest.json"
  accent="#5B9CFF"
  controls="full"
  autoplay loop>
</alembic-viewer>
```

**Déploiement** : copie `viewer/alembic-viewer.js` **et** `viewer/vendor/`
(garder les deux ensemble — le module fait `import './vendor/three.module.js'`).

### Attributs

| Attribut     | Valeurs / défaut                     | Rôle |
|--------------|--------------------------------------|------|
| `src`        | URL de `manifest.json` *(requis)*    | source ; cross-origin ⇒ CORS (voir §5) |
| `autoplay`   | présent = oui                        | démarre la lecture au chargement |
| `loop`       | `"false"`/`"0"` pour couper (défaut : boucle) | |
| `fps`        | nombre                               | force le fps (sinon celui du manifest) |
| `accent`     | couleur CSS (`#5B9CFF`)              | couleur d'accent de l'UI |
| `background` | couleur CSS (`#16161A`)              | fond du viewport 3D |
| `controls`   | `full` \| `minimal` \| `none`        | `minimal` masque toolbar+Lens ; `none` masque tout |
| `wireframe`  | `off` \| `overlay` \| `only`         | état initial du wireframe |

Sous **520 px de large**, le panneau *Lens* et les infos secondaires se masquent
tout seuls (utile en tuile).

### Propriétés (lecture seule)

`ready`, `manifest`, `frameCount`, `currentFrame`, `playing`

### Méthodes

| Méthode | Détail |
|---|---|
| `play()` / `pause()` / `toggle()` | |
| `seek(frameIndex)` | index entier `0..frameCount-1` (met en pause) |
| `seekTime(seconds)` | idem via le temps |
| `setFocalLength(mm)` | focale réelle (dos film 36 mm) — modifie le fov, pas la distance |
| `setWireframe("off"\|"overlay"\|"only")` | |
| `resetView()` | recadre sur la frame courante |
| `screenshot({ scale = 1, type = "image/png" })` | → `Promise<Blob>` |
| `getState()` | → `{ frame, frameCount, playing, fps, focalMm, wireframe }` |
| `load(src)` | change de modèle à chaud |

### Events  (`CustomEvent`, `bubbles: true, composed: true`)

| Event | `detail` |
|---|---|
| `av-ready` | `{ name, frameCount, fps, bbox }` |
| `av-frame` | `{ frame, frameCount, time }` — à chaque changement de frame |
| `av-play` / `av-pause` | `null` |
| `av-focal` | `{ mm, fov }` |
| `av-wireframe` | `{ mode }` |
| `av-error` | `{ message }` |

Exemples React / Vue : `viewer/examples/`.

---

## 4. Embarquer — Option B : iframe

Quand tu **ne peux pas** charger le module dans l'app hôte.

```html
<iframe
  src="/assets/alembic-viewer/embed.html?src=/api/previews/1234/manifest.json&accent=%235B9CFF&controls=full&autoplay=1"
  style="border:0;width:100%;height:480px"
  all* allowfullscreen>
</iframe>
```

Params URL : `src` (requis), `accent`, `background`, `controls`, `autoplay=1`, `loop=0`.

### Pont `postMessage`

Tous les messages portent `{ source: "alembic-viewer" }`.

**hôte → iframe**

```js
iframe.contentWindow.postMessage({
  source: "alembic-viewer", type: "command",
  id: 7,                        // optionnel, repris dans la réponse
  name: "seek", args: [40],
}, "*");
```

`name` ∈ `play` `pause` `toggle` `seek` `seekTime` `setFocalLength`
`setWireframe` `resetView` `getState` `screenshot` `load`.

**iframe → hôte**

```js
addEventListener("message", (e) => {
  if (e.data?.source !== "alembic-viewer") return;
  if (e.data.type === "event")    { /* e.data.name, e.data.detail */ }
  if (e.data.type === "response") { /* e.data.id, e.data.name, ... */ }
});
```

- `event` : `ready` `frame` `play` `pause` `focal` `wireframe` `error` `embed-ready`
- `response` : `screenshot` ⇒ `{ dataUrl }` · `getState` ⇒ `{ state }`

---

## 5. Hosting & CORS

Le navigateur doit pouvoir `fetch()` le `manifest.json` et les `.bin`.

- MIME : `application/json` / `application/octet-stream`.
- Front et API sur des origines différentes ⇒
  `Access-Control-Allow-Origin: <origine du front>` sur ces fichiers.
- Auth : si tes previews sont protégées, sers-les via URL signée courte, ou
  proxifie par le front (le viewer suit juste l'URL qu'on lui donne).
- Gzip serveur : gain faible sur du float32 brut. Le vrai levier reste
  `--decimate` / `--frame-step` au converter.

---

## 6. Limites v1 (assumées)

- **Préchargement complet** de la séquence avant lecture (pas de streaming).
  OK pour des plans courts ; pour une grosse sim → décimer / sous-échantillonner.
- **Pas de compression** des `.bin`. Évolutions possibles : quantization,
  Draco/meshopt, ou bake en morph targets quand la topo est constante.
- Pas d'UV/textures, pas d'axes/gizmo, une seule caméra perspective.

---

## 7. Contenu du paquet

```
WEB_ALEMBIC/
├─ INTEGRATION.md              ← ce fichier
├─ README.md                   quickstart
├─ CHOU_FORMAT.md              spec du bundle .chou
├─ blender_addon/chou_io/      addon Blender import/export .chou (+ chou_core.py = source de vérité du format)
├─ converter/
│   ├─ abc_to_sequence.py      .abc → géométrie seule
│   ├─ scene_to_sequence.py    .chou/.abc/.usd*/.blend → géométrie + matériaux flat
│   ├─ export_chou.py          export .chou headless
│   └─ import_server.py        sert le viewer + import par drag & drop (dev)
└─ viewer/
    ├─ alembic-viewer.js       le custom element + API (≈ 25 ko)
    ├─ vendor/
    │   ├─ three.module.js     three.js r169 (MIT)
    │   └─ OrbitControls.js    patché pour import relatif (MIT)
    ├─ embed.html              hôte iframe + pont postMessage
    ├─ index.html              app de démo (menu modèle + drag & drop .abc)
    ├─ serve.py                serveur statique LAN de dev
    ├─ models/Untitled/        séquence d'exemple (cube animé, 21 frames)
    └─ examples/
        ├─ plain.html          <script> + <alembic-viewer> + API
        ├─ iframe.html         embed iframe + postMessage
        ├─ react.jsx           wrapper React
        └─ vue-kitsu.md        intégration Vue / Kitsu / board PureRef
```
