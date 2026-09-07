# toiture-scan

Métré de toiture à distance à partir des données publiques françaises (IGN LiDAR HD + orthophoto + BD TOPO), avec estimation chiffrée et espace client pour l'artisan.

Objectif métier : supprimer les déplacements de qualification. L'artisan ne se déplace que sur les dossiers qui valent le coup.

---

## Ce que fait l'outil

1. Le particulier saisit son adresse.
2. L'outil localise le bâtiment, affiche l'orthophoto IGN (20 cm) et l'emprise du bâti.
3. Le particulier valide / ajuste l'emprise du toit.
4. Le moteur calcule, à partir du MNS LiDAR HD 50 cm :
   - la **surface réelle** de couverture (pas la surface projetée),
   - la **pente** et l'**orientation** de chaque pan,
   - le **métré linéaire** : faîtage, arêtiers, noues, rives, égout.
5. Le moteur applique la grille de prix de l'artisan → **fourchette d'estimation** + rapport PDF.
6. Le lead part dans le CRM avec toutes les données du toit attachées.

## Ce que l'outil ne fait pas

Il ne produit **pas un devis ferme**. La sortie est une estimation avec fourchette et mentions de réserve (état de la charpente, accès, amiante, complexité de raccords). Un devis ferme signé depuis une vue aérienne est un générateur de litiges. La conversion se fait à la visite, que l'outil a servi à qualifier.

---

## Le point technique qui décide de tout

Une vue satellite donne la surface **projetée au sol**. La surface réelle d'un toit est plus grande, dans un rapport `1 / cos(pente)` :

| Pente | Écart surface réelle vs projetée |
|-------|----------------------------------|
| 30 %  | +4 %   |
| 45°   | +41 %  |
| 60°   | +100 % |

Un outil qui ignore la pente se trompe de 15 à 40 % sur un toit français courant. C'est pour ça que la donnée centrale du projet est le **LiDAR HD de l'IGN**, pas l'imagerie.

Formule retenue, appliquée pixel par pixel sur le MNS :

```
surface_reelle = Σ ( aire_pixel / cos(pente_pixel) )
```

Robuste, sans avoir besoin de segmenter les pans au préalable. La segmentation en pans sert au métré linéaire et à l'affichage.

---

## Architecture

```
Frontend (React + MapLibre GL)
  └── fond ortho IGN WMTS + dessin/ajustement d'emprise
        │
        ▼
API (FastAPI, Python)
  ├── /geocode       → Géoplateforme géocodage
  ├── /batiment      → WFS BD TOPO (emprise + hauteurs toit)
  ├── /metre         → moteur LiDAR (rasterio + numpy)
  └── /estimation    → grille de prix artisan
        │
        ▼
CRM (HubSpot) : lead + propriétés du toit + PDF
```

Python côté backend parce que toute la chaîne géospatiale (rasterio, PDAL, shapely, geopandas) y vit.

**Cache** : les dalles MNS pèsent ~24 Mo. Stockage local ou objet des dalles déjà téléchargées, indexées par nom de dalle. Sur une zone de chalandise départementale, le cache se remplit vite et les calculs deviennent quasi instantanés.

---

## Différenciation

Les calculateurs de toiture existants s'arrêtent à la surface. La surface n'est pas ce qui fait le prix en charpente-couverture : ce sont les **linéaires** (faîtage, arêtiers, noues) et la **complexité** (nombre de pans, croupes, lucarnes, chiens-assis). Un toit à 4 pans avec deux noues coûte bien plus qu'un deux-pans de même surface.

Le moteur doit donc sortir un métré, pas un nombre de m². C'est ce qui rend l'estimation crédible pour l'artisan et l'outil difficile à copier.

Second axe : la chaîne complète. Calculateur → capture de lead → CRM → relance → mesure du taux de transformation. Ce n'est pas un widget, c'est le système d'acquisition de l'artisan.

---

## Roadmap

**Étape 0 — validation (à faire avant tout code produit)**
Prendre 3 à 5 chantiers déjà réalisés par l'artisan, dont il a les métrés réels. Faire tourner le POC dessus. Comparer.
- Écart < 10 % sur la surface → le produit existe.
- Écart > 20 % → revoir la méthode avant d'investir.

C'est le seul jalon qui compte pour l'instant. Voir `poc_toiture.py`.

**Étape 1 — MVP** : adresse → emprise → surface + pente + fourchette, capture email, notification artisan.

**Étape 2 — métré linéaire** : segmentation des pans, faîtage/arêtiers/noues, rapport PDF.

**Étape 3 — espace artisan** : grille de prix paramétrable, liste des demandes, statuts, export CRM.

**Étape 4 — produit** : multi-comptes, l'artisan devient client zéro et vitrine.

---

## Points de vigilance

- **Couverture LiDAR** : ~80 % du territoire fin 2025, complétude annoncée fin 2026. Vérifier la zone de chalandise avant de promettre quoi que ce soit. Prévoir un fallback (voir `SOURCES-DONNEES.md`).
- **ZICAD** : zones interdites à la captation aérienne, données absentes (nodata). Gérer le cas proprement côté UI.
- **Fraîcheur** : une dalle LiDAR peut dater de plusieurs années. Une extension récente n'y sera pas. À croiser avec la date de l'orthophoto.
- **Licence** : données IGN en Etalab 2.0, usage commercial autorisé, mention de la source obligatoire.
- **RGPD** : adresse + email + données de bâti = données personnelles. Registre de traitement, base légale, durée de conservation.

---

## Structure

```
README.md             ce fichier
SOURCES-DONNEES.md    tous les endpoints IGN, vérifiés
poc_toiture.py        script de validation étape 0
requirements.txt      dépendances Python
.gitignore
```

Tout est à la racine : le projet est trop petit pour mériter une arborescence.
