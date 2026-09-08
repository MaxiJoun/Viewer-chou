# WEB_ALEMBIC

Lecteur web pour **animations Alembic et chou** — orbite caméra, **focale réelle
(mm)**, wireframe, timeline. Autonome, embarquable (clone Kitsu, board PureRef…).

- **Intégration / API / format de données → [`INTEGRATION.md`](INTEGRATION.md)**
- **Format `.chou` (anim Alembic + look flat) → [`CHOU_FORMAT.md`](CHOU_FORMAT.md)**
- Ce fichier = démarrage rapide.

```
blender_addon/chou_io/         addon Blender : File > Import/Export > La Chouette Bundle (.chou)
converter/scene_to_sequence.py .chou/.abc/.usd/.blend → manifest.json + frames/*.bin (Blender headless)
viewer/alembic-viewer.js       <alembic-viewer> — custom element, sans build, sans CDN
viewer/embed.html              hôte iframe + pont postMessage
```

`.chou` = zip { `geometry.abc` (l'anim) + `chou.json` (matériaux **flat**) + `textures/` }.
Les matériaux sont volontairement **flat / unlit** (couleur ou texture de base).

Le navigateur ne lit pas le `.abc` directement — il lit la sortie du converter.

---

## Essayer en local

**Le plus simple — import par glisser-déposer** (nécessite Blender installé) :

```bash
python converter/import_server.py 8080
```

Ouvrir l'URL affichée, **glisser un `.chou`, `.abc`, `.usd(c)` ou `.blend` sur la
page** : Blender convertit en tâche de fond et le viewer charge le modèle. Les
`.chou` / `.usd` / `.blend` amènent aussi les **matériaux** (flat : couleur ou
texture de base) ; l'`.abc` reste en gris. (Blender cherché via `$BLENDER`, le
PATH, puis les chemins d'install classiques.)

Contre l'accumulation de modèles de test :
- boutons **🗑** (supprimer le modèle courant) et **vider** (tout) dans la barre
- `--single` : chaque import **remplace** le précédent (jamais de liste)
- `--fresh` : vide `viewer/models/` au démarrage du serveur

```bash
python converter/import_server.py 8080 --single --fresh
```

**Ou à la main** — convertir puis servir en statique :

```bash
blender --background --factory-startup --python converter/abc_to_sequence.py -- \
  --input "Untitled.abc" --outdir "viewer/models/Untitled"
cd viewer && python serve.py 8080
```

Autre modèle : `?model=NAME`. Une séquence d'exemple
(`viewer/models/Untitled/`, cube animé) est déjà incluse.

## Mettre en ligne (GitHub Pages)

Le `viewer/` est 100 % statique. Un workflow (`.github/workflows/pages.yml`)
publie ce dossier à chaque push sur `main`.

1. `git init && git add -A && git commit -m "init"` (déjà fait si tu pars du repo)
2. Créer un repo **public** sur github.com, puis :
   ```bash
   git remote add origin https://github.com/<toi>/<repo>.git
   git branch -M main && git push -u origin main
   ```
3. Repo → **Settings → Pages → Source : GitHub Actions**
4. En ligne sur `https://<toi>.github.io/<repo>/` — ouvrable aussi en `<iframe>`.

**Ajouter un modèle** (pas de backend sur Pages) : convertis en local
(`import_server.py` ou `scene_to_sequence.py`), ce qui écrit
`viewer/models/<nom>/` **et** met à jour `viewer/models.json`, puis
`git add viewer/models && git commit && git push`.

## Embarquer (résumé)

```html
<script type="module" src="/assets/alembic-viewer/alembic-viewer.js"></script>
<alembic-viewer src="/api/previews/1234/manifest.json" autoplay loop></alembic-viewer>
```

Copier `viewer/alembic-viewer.js` **+** `viewer/vendor/` ensemble.
Détails, attributs, méthodes, events, iframe, CORS → [`INTEGRATION.md`](INTEGRATION.md).
Exemples : [`viewer/examples/`](viewer/examples/).

## Contrôles

- souris : orbit (glisser) · dolly (molette) · pan (clic droit)
- **focal (mm)** : slider du panneau *Lens* → change la perspective (≠ molette)
- `W` wireframe · `F` recadrer · `Espace` play/pause · `←`/`→` frame à frame

## Limites v1

Préchargement complet (pas de streaming), `.bin` non compressés, pas d'UV.
Leviers de poids : `--decimate`, `--frame-step`. Voir `INTEGRATION.md` §6.
