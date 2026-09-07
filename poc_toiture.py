#!/usr/bin/env python3
"""
POC toiture-scan — étape 0 : valider la méthode avant de construire le produit.

Chaîne : adresse → bâtiment → dalle MNS LiDAR HD → pente → surface réelle.

Usage :
    python poc_toiture.py "12 rue des Lilas, 14000 Caen"
    python poc_toiture.py "12 rue des Lilas, 14000 Caen" --reel 187

Le seul chiffre qui compte : l'écart entre la surface calculée et le métré
réel de l'artisan. Sous 10 %, le produit existe. Au-dessus de 20 %, la
méthode est à revoir avant d'écrire une ligne de code produit.
"""

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import requests
import rasterio
import rasterio.mask
from pyproj import Transformer
from shapely.geometry import shape, Point, mapping
from shapely.ops import transform as shp_transform

GEOCODE = "https://data.geopf.fr/geocodage/search"
WFS = "https://data.geopf.fr/wfs/ows"
CACHE = Path("cache_dalles")
TIMEOUT = 60

# Nom de la couche d'assemblage des dalles MNS.
# L'IGN l'écrit tantôt avec tiret, tantôt avec underscore selon les pages.
# Le script essaie les deux et garde celle qui répond.
COUCHES_DALLES_MNS = ["IGNF_MNS-LIDAR-HD:dalle", "IGNF_MNS_LIDAR-HD:dalle"]

to_l93 = Transformer.from_crs("EPSG:4326", "EPSG:2154", always_xy=True).transform
to_wgs = Transformer.from_crs("EPSG:2154", "EPSG:4326", always_xy=True).transform


def log(msg):
    print(msg, flush=True)


# --------------------------------------------------------------------------
# 1. Adresse → coordonnées
# --------------------------------------------------------------------------
def geocoder(adresse):
    r = requests.get(
        GEOCODE,
        params={"q": adresse, "index": "address", "limit": 1},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    feats = r.json().get("features", [])
    if not feats:
        sys.exit(f"Adresse introuvable : {adresse}")
    lon, lat = feats[0]["geometry"]["coordinates"]
    label = feats[0]["properties"].get("label", adresse)
    log(f"[1] {label}  →  {lat:.6f}, {lon:.6f}")
    return lon, lat


# --------------------------------------------------------------------------
# 2. Emprise du bâtiment (BD TOPO)
# --------------------------------------------------------------------------
def batiment(lon, lat, marge_deg=0.0008):
    """Bâtiment BD TOPO contenant (ou le plus proche de) le point géocodé."""
    bbox = f"{lat-marge_deg},{lon-marge_deg},{lat+marge_deg},{lon+marge_deg}"
    r = requests.get(
        WFS,
        params={
            "SERVICE": "WFS",
            "VERSION": "2.0.0",
            "REQUEST": "GetFeature",
            "TYPENAMES": "BDTOPO_V3:batiment",
            # WFS 2.0 en EPSG:4326 attend ymin,xmin,ymax,xmax
            "BBOX": f"{bbox},urn:ogc:def:crs:EPSG::4326",
            "outputFormat": "application/json",
            "count": "30",
        },
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    feats = r.json().get("features", [])
    if not feats:
        sys.exit("Aucun bâtiment BD TOPO dans l'emprise. Élargir la marge ?")

    pt = Point(lon, lat)
    contenant = [f for f in feats if shape(f["geometry"]).contains(pt)]
    choisi = (
        contenant[0]
        if contenant
        else min(feats, key=lambda f: shape(f["geometry"]).distance(pt))
    )

    geom = shape(choisi["geometry"])
    props = choisi["properties"]
    geom_l93 = shp_transform(to_l93, geom)

    zmin = props.get("z_min_toit")
    zmax = props.get("z_max_toit")
    log(f"[2] Bâtiment : emprise au sol {geom_l93.area:.1f} m²")
    if zmin and zmax:
        log(f"    toit : z_min {zmin} m, z_max {zmax} m  →  comble {zmax - zmin:.1f} m")
    log(f"    hauteur BD TOPO : {props.get('hauteur')} m")

    return geom_l93, props


# --------------------------------------------------------------------------
# 3. Dalle MNS LiDAR HD couvrant le bâtiment
# --------------------------------------------------------------------------
def trouver_dalle(geom_l93):
    """Interroge le tableau d'assemblage WFS pour localiser la dalle MNS."""
    cx, cy = geom_l93.centroid.x, geom_l93.centroid.y
    lon, lat = to_wgs(cx, cy)
    d = 0.0005
    bbox = f"{lat-d},{lon-d},{lat+d},{lon+d}"

    for couche in COUCHES_DALLES_MNS:
        try:
            r = requests.get(
                WFS,
                params={
                    "SERVICE": "WFS",
                    "VERSION": "2.0.0",
                    "REQUEST": "GetFeature",
                    "TYPENAMES": couche,
                    "BBOX": f"{bbox},urn:ogc:def:crs:EPSG::4326",
                    "outputFormat": "application/json",
                    "count": "5",
                },
                timeout=TIMEOUT,
            )
            if r.status_code != 200:
                continue
            feats = r.json().get("features", [])
            if feats:
                log(f"[3] Couche d'assemblage OK : {couche}")
                return feats[0]["properties"]
        except Exception:
            continue

    log("[3] Aucune dalle MNS trouvée sur cette zone.")
    log("    Deux causes possibles :")
    log("    - le LiDAR HD ne couvre pas encore le secteur")
    log("      (carte : https://macarte.ign.fr/carte/mThSup/diffusionMNxLiDARHD)")
    log("    - le nom de couche a changé ; vérifier via :")
    log("      https://data.geopf.fr/wfs/ows?SERVICE=WFS&VERSION=2.0.0&REQUEST=GetCapabilities")
    return None


def url_dalle(props):
    """Extrait l'URL de téléchargement des propriétés de la dalle."""
    for cle, val in props.items():
        if isinstance(val, str) and val.startswith("http") and ".tif" in val.lower():
            return val
    for cle, val in props.items():
        if isinstance(val, str) and val.startswith("http"):
            return val
    log("    Propriétés de la dalle (aucune URL évidente) :")
    log("    " + json.dumps(props, ensure_ascii=False)[:600])
    return None


def telecharger(url):
    CACHE.mkdir(exist_ok=True)
    dest = CACHE / url.split("/")[-1].split("?")[0]
    if dest.exists():
        log(f"[4] Dalle en cache : {dest.name}")
        return dest
    log(f"[4] Téléchargement {dest.name} (~24 Mo)…")
    with requests.get(url, stream=True, timeout=300) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    log(f"    OK ({dest.stat().st_size / 1e6:.1f} Mo)")
    return dest


# --------------------------------------------------------------------------
# 4. Le calcul
# --------------------------------------------------------------------------
def metrer(chemin_mns, geom_l93, retrait=1.0):
    """
    Surface réelle = Σ ( aire_pixel / cos(pente_pixel) ).

    `retrait` : érosion de l'emprise en mètres. Les bords du MNS sur le
    contour d'un bâtiment mélangent toit et sol, ce qui crée de fausses
    pentes verticales. On rogne pour ne garder que le cœur du toit, puis
    on rapporte le résultat à la surface projetée totale.
    """
    geom_calcul = geom_l93.buffer(-retrait)
    if geom_calcul.is_empty:
        geom_calcul = geom_l93

    with rasterio.open(chemin_mns) as src:
        mns, transform_ = rasterio.mask.mask(
            src, [mapping(geom_calcul)], crop=True, filled=True, nodata=np.nan
        )
        px = abs(src.transform.a)

    z = mns[0].astype("float64")
    if np.all(np.isnan(z)):
        sys.exit("Emprise vide dans le MNS (zone ZICAD, ou hors couverture).")

    # Gradient d'altitude → pente locale
    dzdy, dzdx = np.gradient(z, px)
    pente_rad = np.arctan(np.hypot(dzdx, dzdy))

    valide = ~np.isnan(pente_rad)
    # Au-delà de 75°, on est sur un mur ou un artefact de bord, pas un pan.
    valide &= pente_rad < math.radians(75)

    n = int(valide.sum())
    if n == 0:
        sys.exit("Aucun pixel exploitable après filtrage.")

    aire_px = px * px
    surf_projetee_calcul = n * aire_px
    surf_reelle_calcul = float(np.sum(aire_px / np.cos(pente_rad[valide])))

    # On rapporte à l'emprise complète (le retrait a rogné du toit réel)
    facteur = geom_l93.area / surf_projetee_calcul if surf_projetee_calcul else 1.0
    surface_reelle = surf_reelle_calcul * facteur

    pentes_deg = np.degrees(pente_rad[valide])
    pente_med = float(np.median(pentes_deg))
    coef = surf_reelle_calcul / surf_projetee_calcul

    log("")
    log("[5] Résultat")
    log(f"    emprise au sol        : {geom_l93.area:8.1f} m²")
    log(f"    pente médiane         : {pente_med:8.1f}°  ({math.tan(math.radians(pente_med))*100:.0f} %)")
    log(f"    pente p25 / p75       : {np.percentile(pentes_deg, 25):8.1f}° / {np.percentile(pentes_deg, 75):.1f}°")
    log(f"    coefficient de pente  : {coef:8.3f}")
    log(f"    SURFACE RÉELLE TOIT   : {surface_reelle:8.1f} m²")
    log(f"    (pixels retenus : {n}, résolution {px} m)")

    return {
        "emprise_sol_m2": round(geom_l93.area, 1),
        "pente_mediane_deg": round(pente_med, 1),
        "coefficient_pente": round(coef, 3),
        "surface_reelle_m2": round(surface_reelle, 1),
        "pixels": n,
    }


# --------------------------------------------------------------------------
def main():
    p = argparse.ArgumentParser()
    p.add_argument("adresse")
    p.add_argument("--reel", type=float, help="métré réel de l'artisan, en m²")
    p.add_argument("--retrait", type=float, default=1.0, help="érosion des bords, en m")
    args = p.parse_args()

    lon, lat = geocoder(args.adresse)
    geom, props = batiment(lon, lat)

    dalle_props = trouver_dalle(geom)
    if not dalle_props:
        # Fallback BD TOPO : pente estimée depuis la hauteur de comble
        zmin, zmax = props.get("z_min_toit"), props.get("z_max_toit")
        if zmin and zmax:
            comble = zmax - zmin
            demi_largeur = math.sqrt(geom.area) / 2
            pente = math.degrees(math.atan(comble / demi_largeur))
            surf = geom.area / math.cos(math.radians(pente))
            log("")
            log("[!] Pas de LiDAR ici — estimation dégradée via BD TOPO :")
            log(f"    comble {comble:.1f} m  →  pente ~{pente:.0f}°  →  ~{surf:.0f} m²")
            log("    Précision insuffisante pour chiffrer. Signal, pas mesure.")
        sys.exit(1)

    url = url_dalle(dalle_props)
    if not url:
        sys.exit("URL de dalle introuvable dans la réponse WFS.")

    chemin = telecharger(url)
    res = metrer(chemin, geom, retrait=args.retrait)

    if args.reel:
        ecart = (res["surface_reelle_m2"] - args.reel) / args.reel * 100
        log("")
        log(f"    métré artisan : {args.reel:.1f} m²")
        log(f"    ÉCART         : {ecart:+.1f} %")
        if abs(ecart) < 10:
            log("    → sous 10 %. Le produit existe.")
        elif abs(ecart) < 20:
            log("    → zone grise. Tester d'autres toits avant de conclure.")
        else:
            log("    → au-delà de 20 %. Revoir la méthode avant d'investir.")

    print()
    print(json.dumps(res, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
