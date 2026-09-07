# Sources de données — état vérifié septembre 2026

Toutes les données ci-dessous sont **gratuites, ouvertes (licence Etalab 2.0), sans clé API**.

Point important : les anciennes URLs `wxs.ign.fr` avec clé Géoportail sont **mortes**. Tout est passé sur la Géoplateforme (`data.geopf.fr`) depuis la bascule de mars 2024. Les tutoriels et bouts de code trouvés en ligne antérieurs à cette date sont périmés — ne pas s'y fier.

---

## 1. Géocodage — adresse vers coordonnées

**Géoplateforme (recommandé)**
```
https://data.geopf.fr/geocodage/search?q=12+rue+de+la+Paix+Caen&index=address&limit=1
```
- Limite : 50 req/s par IP
- Sources : BAN + BD TOPO + Parcellaire Express
- Retourne du GeoJSON, WGS84 (lon, lat)

Autocomplétion (pour le champ de saisie du formulaire) :
```
https://data.geopf.fr/geocodage/completion?text=12+rue+de+la&type=StreetAddress
```
- Limite : 10 req/s

**Alternative / fallback : BAN historique**
```
https://api-adresse.data.gouv.fr/search/?q=...&limit=1
```
Même socle de données, autre point d'entrée. Utile en secours.

---

## 2. Orthophoto — l'image que voit le client

**WMTS (tuiles, pour la carte web)**
```
https://data.geopf.fr/wmts?SERVICE=WMTS&VERSION=1.0.0&REQUEST=GetTile
  &LAYER=HR.ORTHOIMAGERY.ORTHOPHOTOS
  &STYLE=normal&FORMAT=image/jpeg
  &TILEMATRIXSET=PM&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}
```
Résolution ~20 cm en métropole. C'est ce qui se branche dans MapLibre GL comme source raster.

GetCapabilities pour lister toutes les couches disponibles :
```
https://data.geopf.fr/wmts?SERVICE=WMTS&VERSION=1.0.0&REQUEST=GetCapabilities
```

**WMS raster (pour extraire une image sur une emprise précise)**
```
https://data.geopf.fr/wms-r/wms?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap
  &LAYERS=HR.ORTHOIMAGERY.ORTHOPHOTOS&CRS=EPSG:2154&BBOX=...&WIDTH=&HEIGHT=&FORMAT=image/png
```

---

## 3. LiDAR HD — le cœur du produit

Programme national IGN. Nuage de points 3D classifié (sol, végétation, **bâtiment**, eau, ouvrages d'art), densité ≥ 10 points/m². Classification faite par l'IGN, rien à refaire.

**Couverture** : ~80 % du territoire métropolitain fin 2025, complétude métropole + DROM (hors Guyane) annoncée fin 2026.
Carte d'avancement : https://macarte.ign.fr/carte/mThSup/diffusionMNxLiDARHD

### 3a. Produits dérivés (à privilégier)

Trois rasters GeoTIFF, dalles de 1×1 km, pas de 50 cm :

| Produit | Contenu | Poids/dalle |
|---------|---------|-------------|
| **MNS** | altitude du sursol : toits, végétation, ouvrages | ~24 Mo |
| **MNT** | altitude du terrain nu | ~24 Mo |
| **MNH** | hauteur = MNS − MNT | ~24 Mo |

**Le MNS est la donnée principale du projet.** Le toit est dedans, à 50 cm de résolution, prêt à l'emploi. Pas besoin de traiter les nuages bruts pour un MVP.

Interfaces de téléchargement :
```
https://cartes.gouv.fr/telechargement/IGNF_MNS-LIDAR-HD
https://cartes.gouv.fr/telechargement/IGNF_MNT-LIDAR-HD
https://cartes.gouv.fr/telechargement/IGNF_MNH-LIDAR-HD
```

Tableaux d'assemblage des dalles via WFS (pour trouver la bonne dalle par coordonnées, programmatiquement) :
```
https://data.geopf.fr/wfs/ows?SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature
  &TYPENAMES=IGNF_MNS-LIDAR-HD:dalle
  &BBOX=<ymin,xmin,ymax,xmax>,urn:ogc:def:crs:EPSG::4326
  &outputFormat=application/json
```
Autres couches d'assemblage : `IGNF_MNT-LIDAR-HD:dalle`, `IGNF_MNH-LIDAR-HD:dalle`, `IGNF_NUAGES-DE-POINTS-LIDAR-HD:dalle` (+ variantes `:bloc`).

⚠️ Le nom exact est écrit tantôt `IGNF_MNS-LIDAR-HD:dalle` (tiret), tantôt `IGNF_MNS_LIDAR-HD:dalle` (underscore) selon les pages IGN. Le GetCapabilities réel fait foi — le vérifier au premier run et figer la valeur.

Flux WMTS ombrés (visualisation seulement, pas de calcul dessus) :
`IGNF_LIDAR-HD_MNS_ELEVATION.ELEVATIONGRIDCOVERAGE.SHADOW` et équivalents MNT / MNH.

### 3b. Nuages de points bruts (optimisation ultérieure)

Format **COPC.LAZ** (LAZ indexé), dalles 1 km², 50–200 Mo. Intérêt majeur : COPC permet de **streamer uniquement l'emprise du bâtiment** sans télécharger la dalle entière, via PDAL :

```json
[
  {
    "type": "readers.copc",
    "filename": "<url_de_la_dalle>.copc.laz",
    "bounds": "([xmin,xmax],[ymin,ymax])"
  },
  {
    "type": "filters.range",
    "limits": "Classification[6:6]"
  },
  "toit.laz"
]
```
`Classification[6:6]` = points classés « bâtiment ». Sortie directe : le nuage du toit seul.

À garder pour la v2 : plus précis que le MNS pour la segmentation des pans et les arêtes, mais plus lourd à opérer. Le MNS suffit pour valider le concept.

Point d'entrée programme : https://geoservices.ign.fr/lidarhd

---

## 4. Emprise du bâtiment

### BD TOPO via WFS
```
https://data.geopf.fr/wfs/ows?SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature
  &TYPENAMES=BDTOPO_V3:batiment
  &BBOX=<ymin,xmin,ymax,xmax>,urn:ogc:def:crs:EPSG::4326
  &outputFormat=application/json&count=20
```

Attributs précieux pour le métier :
- `hauteur` — hauteur du bâtiment
- `z_min_toit`, `z_max_toit` — altitudes basse et haute de la toiture
- `nature`, `usage_1` — type de bâti
- `nombre_d_etages`

**`z_max_toit − z_min_toit` donne la hauteur du comble.** Croisé avec la largeur de l'emprise, ça donne une pente estimée. C'est le **fallback quand le LiDAR n'est pas encore disponible** sur la zone. Moins précis, mais ça évite de bloquer l'utilisateur sur un écran vide.

⚠️ Le WFS accepte 2 couches maximum par requête (`LayerLimit=2`), et renvoie 5000 objets par défaut. Toujours borner par BBOX serrée.

### Parcelle cadastrale (contexte, accès chantier)
```
https://apicarto.ign.fr/api/cadastre/parcelle?geom=<geometrie_geojson_urlencodee>
```
Retourne du GeoJSON. Alternative WFS : `CADASTRALPARCELS.PARCELLAIRE_EXPRESS:parcelle`.

### Zonage urbanisme / PLU (utile pour les contraintes de matériaux)
```
https://apicarto.ign.fr/api/gpu/zone-urba?geom=<geometrie_geojson>
```
Un secteur protégé impose souvent l'ardoise ou la tuile locale. Ça change le prix, et ça montre à l'artisan que l'outil connaît son métier.

---

## 5. Piste à explorer en priorité : potentiel solaire bâtiment

Le WFS Géoplateforme expose une couche `POTENTIEL.SOLAIRE.BATIMENT`.

Si elle contient, comme c'est probable, la **pente et l'orientation par pan de toiture** déjà calculées par l'IGN, elle raccourcit énormément le développement du moteur. À interroger dès le premier jour de dev :

```
https://data.geopf.fr/wfs/ows?SERVICE=WFS&VERSION=2.0.0&REQUEST=DescribeFeatureType
  &TYPENAMES=POTENTIEL.SOLAIRE.BATIMENT
```

Vérifier le schéma, la couverture et la fraîcheur avant d'en dépendre. Mais ça peut faire gagner des semaines.

---

## 6. Altimétrie ponctuelle (secondaire)

```
https://data.geopf.fr/altimetrie/...
```
Limite 5 req/s. Doc : https://geoservices.ign.fr/documentation → « Service Géoplateforme de calcul altimétrique ». Utile pour l'altitude du terrain sans télécharger de dalle, marginal ici.

---

## Systèmes de coordonnées — piège classique

- Les APIs (géocodage, API Carto, WFS en sortie JSON) travaillent en **WGS84 / EPSG:4326**, ordre `(longitude, latitude)`.
- Les dalles LiDAR HD et les calculs métriques sont en **Lambert 93 / EPSG:2154**, ordre `(X, Y)` en mètres.
- Les BBOX WFS 2.0 en EPSG:4326 attendent l'ordre `lat,lon` (`ymin,xmin,ymax,xmax`). C'est contre-intuitif et c'est la source d'erreur numéro un.

**Règle : tout calcul de surface, de distance ou de pente se fait en Lambert 93, jamais en degrés.** Reprojeter en entrée, reprojeter en sortie.

---

## Limites de débit à respecter

| Service | Limite |
|---------|--------|
| Géocodage | 50 req/s |
| Autocomplétion | 10 req/s |
| Recherche | 5 req/s |
| Altimétrie | 5 req/s |

Disponibilité annoncée : 99,5 %. Prévoir un cache et une dégradation propre — pas d'écran blanc si l'IGN tousse.

---

## Attribution obligatoire

Licence Etalab 2.0 : usage commercial autorisé, **mention de la source requise**.

À afficher dans le pied de page et sur les rapports PDF :
> Sources : IGN — BD TOPO®, LiDAR HD, BD ORTHO® — licence Etalab 2.0
