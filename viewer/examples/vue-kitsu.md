# Intégrer `<alembic-viewer>` dans un frontend type Kitsu (Vue)

Kitsu (et le clone maison) est une SPA **Vue**. Le composant est un *custom element*
natif : Vue le rend tel quel, il suffit de dire au compilateur de ne pas s'en méfier.

---

## 1. Déclarer le custom element

**Vue 3** — `vite.config.js` (ou `vue.config.js` en Vue CLI) :

```js
// vite
export default defineConfig({
  plugins: [vue({
    template: { compilerOptions: { isCustomElement: (tag) => tag === 'alembic-viewer' } },
  })],
});
```

**Vue 2** :

```js
Vue.config.ignoredElements = ['alembic-viewer'];
```

## 2. Charger le module une fois

Copier `alembic-viewer.js` + le dossier `vendor/` dans les assets statiques
(`/public/alembic-viewer/…`) puis, dans `main.js` :

```js
import '/alembic-viewer/alembic-viewer.js'; // side-effect: enregistre <alembic-viewer>
```

## 3. Un composant de preview

```vue
<!-- AlembicPreview.vue -->
<template>
  <div class="alembic-preview">
    <alembic-viewer
      ref="viewer"
      :src="manifestUrl"
      accent="#5B9CFF"
      controls="full"
      autoplay
      @av-ready="onReady"
      @av-frame="onFrame"
    />
  </div>
</template>

<script>
export default {
  name: 'AlembicPreview',
  props: {
    // URL vers manifest.json — voir INTEGRATION.md pour le format
    manifestUrl: { type: String, required: true },
  },
  data: () => ({ frame: 0, frameCount: 0 }),
  methods: {
    onReady(e) { this.frameCount = e.detail.frameCount; },
    onFrame(e) { this.frame = e.detail.frame; this.$emit('frame', e.detail); },
    // API impérative depuis le parent :
    seek(f) { this.$refs.viewer.seek(f); },
    play()  { this.$refs.viewer.play(); },
    pause() { this.$refs.viewer.pause(); },
    async screenshot() { return this.$refs.viewer.screenshot({ scale: 2 }); },
  },
};
</script>

<style scoped>
.alembic-preview { width: 100%; height: 100%; min-height: 320px; border-radius: 10px; overflow: hidden; }
</style>
```

> ⚠️ Vue écoute les events DOM natifs kebab-case : `@av-ready`, `@av-frame`.
> Les events du composant sont émis avec `bubbles: true, composed: true`,
> donc ils traversent le Shadow DOM et remontent normalement.

## 4. Où le brancher dans Kitsu

Kitsu associe des **previews** (révisions) à une tâche. Deux options :

### a. Nouveau type de preview `alembic`
Dans le composant qui choisit le player selon `preview.extension`
(cherche `preview-player`, `model-viewer`, `.glb`, `.obj` dans le code du front) :

```js
// pseudo
if (isAlembicSequence(preview)) {
  return h('AlembicPreview', { props: { manifestUrl: previewManifestUrl(preview) } });
}
```

`previewManifestUrl(preview)` renvoie l'URL servie par le backend (voir §5).

### b. Onglet / panneau custom
Si tu ne veux pas toucher au routeur de previews : un onglet "3D" sur la page
de tâche qui monte `<AlembicPreview :manifest-url="…">`. Zéro impact sur
l'existant.

### c. Tuile sur le board type PureRef
Le composant marche dans un `<div>` positionné/redimensionné librement. Pour
une tuile compacte, passe `controls="minimal"` ou `controls="none"` ; en
dessous de 520 px de large il masque le panneau *Lens* automatiquement.

```vue
<alembic-viewer
  :src="tile.manifestUrl"
  controls="none"
  loop
  autoplay
  :style="{ position:'absolute', left: tile.x+'px', top: tile.y+'px',
            width: tile.w+'px', height: tile.h+'px' }" />
```

## 5. Servir les séquences depuis le backend

Le converter produit `manifest.json` + `frames/*.bin`. Le backend doit les
servir en statique (mêmes règles qu'un attachment) :

- content-type : `application/json` pour le manifest, `application/octet-stream` pour les `.bin`
- si le front et l'API sont sur des domaines différents :
  `Access-Control-Allow-Origin: <origine du front>`
- pas d'auth par cookie tierce ? sers via une URL signée courte, ou proxy
  par le front.

Structure recommandée côté stockage :

```
<storage>/previews/<preview_id>/manifest.json
<storage>/previews/<preview_id>/frames/frame_0000.bin
...
```

et `manifestUrl = ${API}/previews/${preview.id}/manifest.json`.
