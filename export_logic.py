import os
import subprocess
from qgis.core import (
    QgsGeometry,
    QgsVectorLayer,
    QgsMapLayerStyle,
    QgsFeature,
    QgsProject,
    QgsMapLayer,
    QgsWkbTypes,
    QgsRasterLayer,
    QgsVectorFileWriter,
    QgsCoordinateTransformContext,
    QgsCoordinateTransform,
    QgsCoordinateReferenceSystem,
    QgsRasterFileWriter,
    QgsRasterPipe,
    QgsRectangle,
    QgsApplication,
    Qgis,
    QgsLayerTreeGroup,
)
from qgis.PyQt.QtWidgets import QFileDialog, QMessageBox, QProgressDialog, QInputDialog
from qgis.PyQt.QtCore import Qt
from qgis.gui import QgsMapToolEmitPoint, QgsRubberBand
from qgis.PyQt.QtGui import QColor
import processing
from qgis.core import QgsDataSourceUri
import datetime          
from decimal import Decimal  
from .compat import QT_WINDOW_MODAL
import gc
from qgis.PyQt.QtWidgets import QApplication



def _copier_style_vers_gpkg(layer_source: QgsVectorLayer, layer_gpkg: QgsVectorLayer):
    """Copie le style QML de la couche source vers le GPKG (table layer_styles)."""
    if not layer_source.isValid() or not layer_gpkg.isValid():
        return

    # 1. Récupère le QML XML du style courant
    sm_src = layer_source.styleManager()
    qml_xml = sm_src.style(sm_src.currentStyle()).xmlData()
    if not qml_xml:
        return

    # 2. Applique ce style à la couche GPKG
    style = QgsMapLayerStyle(qml_xml)
    sm_dst = layer_gpkg.styleManager()
    if "default" in sm_dst.styles():
        sm_dst.removeStyle("default")
    sm_dst.addStyle("default", style)
    sm_dst.setCurrentStyle("default")

    # 3. Sauvegarde dans la base du GeoPackage
    layer_gpkg.saveStyleToDatabase("default", "Style par defaut", True, "")
    print("  Style copie dans le GeoPackage")


def _sauvegarder_zone_sur_disque(zone_layer: QgsVectorLayer, chemin: str):
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = "GPKG"
    options.layerName = "zone"
    options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteFile
    QgsVectorFileWriter.writeAsVectorFormatV3(
        zone_layer,
        chemin,
        QgsCoordinateTransformContext(),
        options
    )

def _supprimer_ancien_gpkg_si_existe(chemin_gpkg: str) -> bool:
    """
    Supprime l'ancien GeoPackage si on relance un export avec le meme nom.
    Retire aussi les anciennes couches chargees dans QGIS pour eviter le verrouillage.
    """

    if not chemin_gpkg or not os.path.exists(chemin_gpkg):
        return True

    chemin_norm = os.path.normcase(os.path.abspath(chemin_gpkg)).replace("\\", "/")

    ids_a_supprimer = []

    for layer in QgsProject.instance().mapLayers().values():
        try:
            source = layer.source()
            source_norm = os.path.normcase(source).replace("\\", "/")

            if chemin_norm in source_norm:
                ids_a_supprimer.append(layer.id())

        except Exception:
            pass

    if ids_a_supprimer:
        print(f"Anciennes couches du GeoPackage retirees : {len(ids_a_supprimer)}")
        QgsProject.instance().removeMapLayers(ids_a_supprimer)
        QApplication.processEvents()
        gc.collect()

    fichiers_a_supprimer = [
        chemin_gpkg + "-wal",
        chemin_gpkg + "-shm",
        chemin_gpkg + "-journal",
        chemin_gpkg,
    ]

    for fichier in fichiers_a_supprimer:
        if os.path.exists(fichier):
            try:
                os.remove(fichier)
                print(f"Fichier supprime : {fichier}")
            except Exception as e:
                print(f"Impossible de supprimer {fichier} : {e}")
                return False

    return True


def _sauvegarder_zone_dans_gpkg(zone_layer: QgsVectorLayer, chemin_gpkg: str) -> bool:
    """
    Enregistre la zone d'etude dans le GeoPackage final.
    """

    if zone_layer is None or not zone_layer.isValid():
        print("Zone d'etude invalide : impossible de l'enregistrer")
        return False

    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = "GPKG"
    options.layerName = "zone_etude"

    options.actionOnExistingFile = (
        QgsVectorFileWriter.CreateOrOverwriteLayer
        if os.path.exists(chemin_gpkg)
        else QgsVectorFileWriter.CreateOrOverwriteFile
    )

    resultat = QgsVectorFileWriter.writeAsVectorFormatV3(
        zone_layer,
        chemin_gpkg,
        QgsProject.instance().transformContext(),
        options
    )

    if resultat[0] != QgsVectorFileWriter.NoError:
        print(f"Erreur enregistrement zone_etude : {resultat}")
        return False

    print("Zone d'etude enregistree dans le GeoPackage")
    return True


import shutil
import math
# 
# INFOS RASTER : type, bandes, nodata, resolution
# Remplace _detecter_nb_bandes
# 
def _infos_raster(chemin_tif: str) -> dict:
    rl = QgsRasterLayer(chemin_tif, "info")
    info = {
        "valid": False,
        "nb_bandes": 1,
        "gdal_type": "Float32",
        "nodata": None,
        "has_alpha": False,
        "res_x": 1.0,
        "res_y": 1.0,
        "width": 0,
        "height": 0,
    }
    if not rl.isValid():
        return info
    dp = rl.dataProvider()
    info["valid"] = True
    info["nb_bandes"] = dp.bandCount()
    info["res_x"] = abs(rl.rasterUnitsPerPixelX())
    info["res_y"] = abs(rl.rasterUnitsPerPixelY())
    info["width"] = rl.width()
    info["height"] = rl.height()
    mapping = {
        Qgis.Byte: "Byte",
        Qgis.UInt16: "UInt16",
        Qgis.Int16: "Int16",
        Qgis.UInt32: "UInt32",
        Qgis.Int32: "Int32",
        Qgis.Float32: "Float32",
        Qgis.Float64: "Float64",
    }
    info["gdal_type"] = mapping.get(dp.dataType(1), "Float32")
    nd = dp.sourceNoDataValue(1)
    if nd is not None and not math.isnan(nd):
        info["nodata"] = nd
    if dp.bandCount() == 4:
        info["has_alpha"] = True
    return info


# SECURITE RASTER : résolution finale selon emprise + résolution utilisateur
def _calculer_resolution_raster_securisee(
    bbox,
    res_x_native: float,
    res_y_native: float,
    resolution_utilisateur: float,
    max_pixels: int = 50_000_000
):
    """
    Calcule une résolution finale sécurisée.

    Logique :
    - on part de la résolution demandée par l'utilisateur ;
    - on évite de descendre sous la résolution native du raster ;
    - si l'emprise est trop grande, on propose une résolution plus grossière.
    """

    largeur = abs(float(bbox.width()))
    hauteur = abs(float(bbox.height()))

    res_x_native = abs(float(res_x_native))
    res_y_native = abs(float(res_y_native))

    if res_x_native <= 0:
        res_x_native = 1.0

    if res_y_native <= 0:
        res_y_native = 1.0

    resolution_native = max(res_x_native, res_y_native)

    try:
        resolution_utilisateur = abs(float(str(resolution_utilisateur).replace(",", ".")))
    except Exception:
        resolution_utilisateur = resolution_native

    if resolution_utilisateur <= 0:
        resolution_utilisateur = resolution_native

    if largeur <= 0 or hauteur <= 0:
        return {
            "resolution_utilisateur": resolution_utilisateur,
            "resolution_native": resolution_native,
            "resolution_finale": max(resolution_utilisateur, resolution_native),
            "nb_cols_utilisateur": 1,
            "nb_rows_utilisateur": 1,
            "nb_pixels_utilisateur": 1,
            "nb_cols_final": 1,
            "nb_rows_final": 1,
            "nb_pixels_final": 1,
            "resolution_trop_fine_site": False,
            "resolution_plus_fine_que_native": resolution_utilisateur < resolution_native,
            "resolution_modifiee": False,
        }

    # Taille qui serait produite avec la résolution demandée par l'utilisateur
    nb_cols_utilisateur = max(1, int(math.ceil(largeur / resolution_utilisateur)))
    nb_rows_utilisateur = max(1, int(math.ceil(hauteur / resolution_utilisateur)))
    nb_pixels_utilisateur = nb_cols_utilisateur * nb_rows_utilisateur

    # On ne veut pas sur-échantillonner le raster source.
    # Exemple : utilisateur demande 0.25 m, raster natif 1 m -> on garde minimum 1 m.
    resolution_base = max(resolution_utilisateur, resolution_native)

    resolution_finale = resolution_base

    resolution_trop_fine_site = (
        max_pixels is not None
        and max_pixels > 0
        and nb_pixels_utilisateur > max_pixels
    )

    if resolution_trop_fine_site:
        # Formule :
        # pixels = largeur * hauteur / resolution²
        # donc resolution minimale = sqrt((largeur * hauteur) / max_pixels)
        resolution_securite = math.sqrt((largeur * hauteur) / float(max_pixels))

        # Résolution finale = la plus grossière entre :
        # - résolution utilisateur
        # - résolution native
        # - résolution sécurité taille
        resolution_finale = max(resolution_utilisateur, resolution_native, resolution_securite)

    nb_cols_final = max(1, int(math.ceil(largeur / resolution_finale)))
    nb_rows_final = max(1, int(math.ceil(hauteur / resolution_finale)))
    nb_pixels_final = nb_cols_final * nb_rows_final

    # Sécurité contre les dépassements dus aux arrondis
    while max_pixels and max_pixels > 0 and nb_pixels_final > max_pixels:
        resolution_finale *= 1.01
        nb_cols_final = max(1, int(math.ceil(largeur / resolution_finale)))
        nb_rows_final = max(1, int(math.ceil(hauteur / resolution_finale)))
        nb_pixels_final = nb_cols_final * nb_rows_final

    return {
        "resolution_utilisateur": resolution_utilisateur,
        "resolution_native": resolution_native,
        "resolution_finale": resolution_finale,

        "nb_cols_utilisateur": nb_cols_utilisateur,
        "nb_rows_utilisateur": nb_rows_utilisateur,
        "nb_pixels_utilisateur": nb_pixels_utilisateur,

        "nb_cols_final": nb_cols_final,
        "nb_rows_final": nb_rows_final,
        "nb_pixels_final": nb_pixels_final,

        "resolution_trop_fine_site": resolution_trop_fine_site,
        "resolution_plus_fine_que_native": resolution_utilisateur < resolution_native,
        "resolution_modifiee": resolution_finale > resolution_utilisateur * 1.000001,
    }

# SECURITE WMS : résolution finale selon emprise + résolution utilisateur
def _calculer_resolution_wms_securisee(
    bbox,
    resolution_utilisateur: float,
    max_pixels: int = 50_000_000
):
    """
    Calcule une résolution WMS sécurisée.

    Logique :
    - on part de la résolution choisie par l'utilisateur ;
    - on estime le nombre de pixels sur l'emprise ;
    - si le nombre de pixels dépasse max_pixels,
      on propose une résolution plus grossière.
    """

    largeur = abs(float(bbox.width()))
    hauteur = abs(float(bbox.height()))

    try:
        resolution_utilisateur = abs(float(str(resolution_utilisateur).replace(",", ".")))
    except Exception:
        resolution_utilisateur = 1.0

    if resolution_utilisateur <= 0:
        resolution_utilisateur = 1.0

    if largeur <= 0 or hauteur <= 0:
        return {
            "resolution_utilisateur": resolution_utilisateur,
            "resolution_finale": resolution_utilisateur,
            "nb_cols_utilisateur": 1,
            "nb_rows_utilisateur": 1,
            "nb_pixels_utilisateur": 1,
            "nb_cols_final": 1,
            "nb_rows_final": 1,
            "nb_pixels_final": 1,
            "resolution_trop_fine_site": False,
            "resolution_modifiee": False,
        }

    nb_cols_utilisateur = max(1, int(math.ceil(largeur / resolution_utilisateur)))
    nb_rows_utilisateur = max(1, int(math.ceil(hauteur / resolution_utilisateur)))
    nb_pixels_utilisateur = nb_cols_utilisateur * nb_rows_utilisateur

    resolution_finale = resolution_utilisateur

    resolution_trop_fine_site = (
        max_pixels is not None
        and max_pixels > 0
        and nb_pixels_utilisateur > max_pixels
    )

    if resolution_trop_fine_site:
        # pixels = largeur * hauteur / resolution²
        # donc resolution minimale = sqrt((largeur * hauteur) / max_pixels)
        resolution_securite = math.sqrt((largeur * hauteur) / float(max_pixels))
        resolution_finale = max(resolution_utilisateur, resolution_securite)

    nb_cols_final = max(1, int(math.ceil(largeur / resolution_finale)))
    nb_rows_final = max(1, int(math.ceil(hauteur / resolution_finale)))
    nb_pixels_final = nb_cols_final * nb_rows_final

    # Sécurité contre les petits dépassements dus aux arrondis
    while max_pixels and max_pixels > 0 and nb_pixels_final > max_pixels:
        resolution_finale *= 1.01
        nb_cols_final = max(1, int(math.ceil(largeur / resolution_finale)))
        nb_rows_final = max(1, int(math.ceil(hauteur / resolution_finale)))
        nb_pixels_final = nb_cols_final * nb_rows_final

    return {
        "resolution_utilisateur": resolution_utilisateur,
        "resolution_finale": resolution_finale,

        "nb_cols_utilisateur": nb_cols_utilisateur,
        "nb_rows_utilisateur": nb_rows_utilisateur,
        "nb_pixels_utilisateur": nb_pixels_utilisateur,

        "nb_cols_final": nb_cols_final,
        "nb_rows_final": nb_rows_final,
        "nb_pixels_final": nb_pixels_final,

        "resolution_trop_fine_site": resolution_trop_fine_site,
        "resolution_modifiee": resolution_finale > resolution_utilisateur * 1.000001,
    }


# GDAL : cherche n'importe quel executable (gdalwarp, gdal_translate, gdaladdo...)
def _gdal_exe(nom: str) -> str:
    exe = shutil.which(nom)
    if exe:
        return exe
    qgis_bin = QgsApplication.applicationDirPath()
    candidats = [
        os.path.join(qgis_bin, f"{nom}.exe"),
        os.path.join(qgis_bin, nom),
        os.path.join(os.path.normpath(os.path.join(qgis_bin, "..")), "bin", f"{nom}.exe"),
        os.path.join(os.path.normpath(os.path.join(qgis_bin, "..")), "bin", nom),
        rf"C:\OSGeo4W\bin\{nom}.exe",
        rf"C:\OSGeo4W64\bin\{nom}.exe",
    ]
    for c in candidats:
        c = os.path.normpath(c)
        if os.path.exists(c):
            return c
    return None

# CLIP RASTER LOCAL : compression + tuilage + alignement
def _clipper_raster_avec_gdalwarp(
    chemin_source: str,
    chemin_zone_tmp: str,
    chemin_raster_tmp: str,
    resolution: float = None,
) -> bool:
    gdalwarp = _gdal_exe("gdalwarp")

    if gdalwarp is None:
        print("  gdalwarp non trouve")
        return False

    infos = _infos_raster(chemin_source)

    if not infos["valid"]:
        print("  Raster source invalide")
        return False

    cmd = [
        gdalwarp,
        "-of", "GTiff",
        "-cutline", chemin_zone_tmp,
        "-cl", "zone",
        "-crop_to_cutline",
        "-wo", "CUTLINE_ALL_TOUCHED=TRUE",
        "-co", "TILED=YES",
        "-co", "COMPRESS=LZW",
        "-co", "BIGTIFF=IF_NEEDED",
        "-overwrite",
    ]

    # Application réelle de la résolution finale
    if resolution is not None and resolution > 0:
        cmd += ["-tr", str(resolution), str(resolution)]
        print(f"  Resolution appliquee par gdalwarp : {resolution:.4f}")

    if infos["nodata"] is not None:
        cmd += ["-dstnodata", str(infos["nodata"])]

    cmd += [chemin_source, chemin_raster_tmp]

    print(f"  Commande : {' '.join(cmd)}")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        if result.stdout:
            print(f"  stdout : {result.stdout.strip()}")

        if result.stderr:
            print(f"  stderr : {result.stderr.strip()}")

        return result.returncode == 0

    except Exception as e:
        print(f"  Erreur gdalwarp : {e}")
        return False




# INTEGRATION GPKG : type natif + pyramides
def _integrer_raster_dans_gpkg(
    chemin_tif: str,
    chemin_gpkg: str,
    nom_table: str,
    generer_overviews: bool = True,
) -> bool:
    gdal_translate = _gdal_exe("gdal_translate")
    if gdal_translate is None:
        print("  gdal_translate non trouve")
        return False
    infos = _infos_raster(chemin_tif)
    gdal_type = infos["gdal_type"]
    print(f"  Type detecte : {gdal_type} ({infos['nb_bandes']} bandes)")
    cmd = [
        gdal_translate,
        "-of", "GPKG",
        "-ot", gdal_type,
        "-co", f"RASTER_TABLE={nom_table}",
        "-co", "APPEND_SUBDATASET=YES",
        "-co", "BLOCKXSIZE=256",
        "-co", "BLOCKYSIZE=256",
    ]

    cmd += [chemin_tif, chemin_gpkg]
    print(f"  Commande : {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.stdout:
            print(f"  stdout : {result.stdout.strip()}")
        if result.stderr:
            print(f"  stderr : {result.stderr.strip()}")
        if result.returncode != 0:
            return False
        # Pyramides (niveaux dynamiques selon la taille)
        if generer_overviews:
            gdaladdo = _gdal_exe("gdaladdo")
            if gdaladdo:
                w, h = infos["width"], infos["height"]
                niveaux = []
                for o in [2, 4, 8, 16]:
                    if w // o >= 2 and h // o >= 2:
                        niveaux.append(str(o))
                if niveaux:
                    ds = f"GPKG:{chemin_gpkg}:{nom_table}"
                    cmd_o = [gdaladdo, "-r", "nearest", ds] + niveaux
                    print(f"  Pyramides : {' '.join(cmd_o)}")
                    ro = subprocess.run(cmd_o, capture_output=True, text=True, timeout=300)
                    if ro.returncode == 0:
                        print(f"  Pyramides OK ({', '.join(niveaux)})")
                    else:
                        print(f"  [WARN] pyramides : {ro.stderr.strip()}")
                else:
                    print("  Image trop petite -> pas de pyramides")
        return True 
    except Exception as e:
        print(f"  Erreur integration GPKG : {e}")
        return False
    

# EXPORT WMS + compression post-traitement
def _exporter_wms_en_tif(
    layer: QgsRasterLayer,
    bbox,
    crs: QgsCoordinateReferenceSystem,
    chemin_tif: str,
    resolution: float,
    parent=None
) -> bool:
    try:
        largeur_m = bbox.width()
        hauteur_m = bbox.height()
        nb_cols = max(1, int(largeur_m / resolution))
        nb_rows = max(1, int(hauteur_m / resolution))
        nb_pixels = nb_cols * nb_rows
        print(f"  Zone : {largeur_m:.0f}m x {hauteur_m:.0f}m")
        print(f"  Resolution : {resolution}m/px")
        print(f"  Taille : {nb_cols}x{nb_rows} px ({nb_pixels:,} pixels)")
        if nb_pixels > 50_000_000:
            r = QMessageBox.question(
                parent, "Image tres grande",
                f"{nb_cols}x{nb_rows} px ({nb_pixels/1_000_000:.0f} Mpx)\n"
                f"Cela peut bloquer QGIS.\nContinuer ?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if r == QMessageBox.No:
                print("  Export annule")
                return False
        pipe = QgsRasterPipe()
        if not pipe.set(layer.dataProvider().clone()):
            print("  Impossible de cloner le provider WMS")
            return False
        writer = QgsRasterFileWriter(chemin_tif)
        writer.setOutputFormat("GTiff")
        error = writer.writeRaster(pipe, nb_cols, nb_rows, bbox, crs)
        if error != QgsRasterFileWriter.NoError:
            print(f"  Erreur export WMS : code {error}")
            return False
        print("  WMS exporte brut")
        # Compression post-export
        gt = _gdal_exe("gdal_translate")
        if gt:
            fd, compressed = tempfile.mkstemp(suffix="_cmp.tif")
            os.close(fd)

            if os.path.exists(compressed):
                os.remove(compressed)
            cmd = [
                gt, "-of", "GTiff",
                "-co", "TILED=YES",
                "-co", "COMPRESS=LZW",
                "-co", "BIGTIFF=IF_NEEDED",
                chemin_tif, compressed,
            ]
            print("  Compression TIF...")
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if r.returncode == 0:
                os.replace(compressed, chemin_tif)
                print("  Compression OK")
            else:
                os.remove(compressed)
                print(f"  [WARN] compression : {r.stderr.strip()}")
        return True
    except Exception as e:
        print(f"  Exception export WMS : {e}")
        return False
    
# SCR

def _forcer_scr_raster(chemin_tif: str, epsg: str) -> bool:
    """
    Force le SCR d'un raster sans reprojeter les pixels.
    Utile quand le raster est deja dans le bon systeme mais mal declare.
    """

    from osgeo import gdal, osr

    ds = gdal.Open(chemin_tif, gdal.GA_Update)

    if ds is None:
        print(f"Impossible d'ouvrir le raster pour forcer le SCR : {chemin_tif}")
        return False

    srs = osr.SpatialReference()
    srs.SetFromUserInput(epsg)

    ds.SetProjection(srs.ExportToWkt())
    ds.FlushCache()
    ds = None

    print(f"SCR force sur {epsg} pour : {chemin_tif}")
    return True

# Buffer 10 m

def _creer_buffer_decoupage(zone_layer_2154, distance_m=10):
    """
    Crée un buffer autour de la zone d'étude pour le découpage.
    La couche doit être en EPSG:2154 pour que la distance soit en mètres.
    """
    if distance_m <= 0:
        return zone_layer_2154

    resultat = processing.run(
        "native:buffer",
        {
            'INPUT': zone_layer_2154,
            'DISTANCE': distance_m,
            'SEGMENTS': 12,
            'END_CAP_STYLE': 0,
            'JOIN_STYLE': 0,
            'MITER_LIMIT': 2,
            'DISSOLVE': True,
            'OUTPUT': 'memory:'
        }
    )

    return resultat['OUTPUT']

def _reprojeter_masque_decoupage(zone_layer, crs_cible):
    """
    Reprojette le masque de découpage dans le SCR de la couche à découper.
    """
    if zone_layer.crs() == crs_cible:
        return zone_layer

    resultat = processing.run(
        "native:reprojectlayer",
        {
            'INPUT': zone_layer,
            'TARGET_CRS': crs_cible,
            'OUTPUT': 'memory:'
        }
    )

    return resultat['OUTPUT']


# VECTEURS TUILES PLAN IGN / XYZ

ZOOM_VECTEUR_TUILE_PLAN_IGN = 17
RESOLUTION_WEBMERCATOR_ZOOM0 = 156543.03392804097


def _est_vecteur_tuile(layer):
    """
    Vérifie si la couche est une couche vecteur tuile QGIS.
    """
    return (
        hasattr(QgsMapLayer, "VectorTileLayer")
        and layer.type() == QgsMapLayer.VectorTileLayer
    )


def _resolution_depuis_zoom_vecteur_tuile(zoom):
    """
    Résolution en mètres/pixel pour une source XYZ / WebMercator.
    Zoom 16 ≈ 2.39 m/pixel.
    """
    return RESOLUTION_WEBMERCATOR_ZOOM0 / (2 ** zoom)

import os
import tempfile

from qgis.core import QgsMapSettings, QgsMapRendererCustomPainterJob
from qgis.PyQt.QtCore import QSize
from qgis.PyQt.QtGui import QImage, QPainter, QColor

def _exporter_vecteur_tuile_plan_ign_en_tif(layer, bbox, crs, chemin_tif, parent=None):
    """
    Exporte une couche vecteur tuile Plan IGN / XYZ en GeoTIFF géoréférencé.

    L'utilisateur ne choisit pas la résolution.
    Elle est fixée automatiquement par ZOOM_VECTEUR_TUILE_PLAN_IGN.
    """

    try:
        from osgeo import gdal
    except Exception as e:
        print(f"  ERREUR GDAL indisponible : {e}")
        return False

    try:
        if bbox is None or bbox.isEmpty():
            print("  ERREUR : emprise vide pour export vecteur tuile")
            return False

        resolution = _resolution_depuis_zoom_vecteur_tuile(
            ZOOM_VECTEUR_TUILE_PLAN_IGN
        )

        largeur_px = max(1, int(bbox.width() / resolution))
        hauteur_px = max(1, int(bbox.height() / resolution))
        nb_pixels = largeur_px * hauteur_px

        print(f"  Zoom vecteur tuile : {ZOOM_VECTEUR_TUILE_PLAN_IGN}")
        print(f"  Taille export      : {largeur_px}x{hauteur_px} px ({nb_pixels:,} pixels)")

        if nb_pixels > 50_000_000:
            reponse = QMessageBox.question(
                parent,
                "Image très grande",
                f"L'export du Plan IGN ferait {largeur_px}x{hauteur_px} px "
                f"({nb_pixels / 1_000_000:.0f} mégapixels).\n\n"
                f"Cela peut être très long ou bloquer QGIS.\n\n"
                f"Continuer quand même ?",
                QMessageBox.Yes | QMessageBox.No
            )

            if reponse == QMessageBox.No:
                print("  Export vecteur tuile annulé par l'utilisateur")
                return False

        image = QImage(
            QSize(largeur_px, hauteur_px),
            QImage.Format_ARGB32_Premultiplied
        )
        image.fill(QColor(255, 0, 0, 255))

        settings = QgsMapSettings()
        settings.setLayers([layer])
        settings.setExtent(bbox)
        settings.setDestinationCrs(crs)
        settings.setOutputSize(QSize(largeur_px, hauteur_px))
        settings.setBackgroundColor(QColor(255, 0,0, 255))
        settings.setFlag(QgsMapSettings.Antialiasing, True)

        painter = QPainter(image)
        job = QgsMapRendererCustomPainterJob(settings, painter)
        job.start()
        job.waitForFinished()
        painter.end()

        fd_png, chemin_png_tmp = tempfile.mkstemp(
            suffix="_plan_ign_vecteur_tuile.png"
        )
        os.close(fd_png)

        if os.path.exists(chemin_png_tmp):
            os.remove(chemin_png_tmp)

        image.save(chemin_png_tmp, "PNG")

        if not os.path.exists(chemin_png_tmp):
            print("  ERREUR : PNG temporaire non créé")
            return False

        if os.path.exists(chemin_tif):
            os.remove(chemin_tif)

        if crs.authid():
            srs = crs.authid()
        else:
            srs = crs.toWkt()

        options_gdal = gdal.TranslateOptions(
            format="GTiff",
            outputSRS=srs,
            outputBounds=[
                bbox.xMinimum(),
                bbox.yMaximum(),
                bbox.xMaximum(),
                bbox.yMinimum()
            ],
            creationOptions=[
                "TILED=YES",
                "COMPRESS=DEFLATE",
                "BIGTIFF=IF_SAFER"
            ]
        )

        ds = gdal.Translate(
            chemin_tif,
            chemin_png_tmp,
            options=options_gdal
        )

        if ds is None:
            print("  ERREUR : gdal.Translate a échoué")
            return False

        ds = None


        if os.path.exists(chemin_png_tmp):
            os.remove(chemin_png_tmp)

        if not os.path.exists(chemin_tif):
            print("  ERREUR : GeoTIFF vecteur tuile non créé")
            return False
        # Force le SCR uniquement pour le GeoTIFF Plan IGN
        if not _forcer_scr_raster(chemin_tif, "EPSG:3857"):
            print("  ERREUR : impossible de forcer le SCR EPSG:3857 sur Plan IGN")
            return False

        print(f"  GeoTIFF Plan IGN créé : {chemin_tif}")
        return True

    except Exception as e:
        print(f"  ERREUR export vecteur tuile Plan IGN : {e}")
        import traceback
        traceback.print_exc()
        return False
    
def _creer_masque_temporaire(zone_layer: QgsVectorLayer, suffixe: str = "_masque.gpkg") -> str:
    """
    Sauvegarde une couche masque dans un GeoPackage temporaire
    et retourne le chemin du fichier.
    """

    fd, chemin_tmp = tempfile.mkstemp(suffix=suffixe)
    os.close(fd)

    if os.path.exists(chemin_tmp):
        os.remove(chemin_tmp)

    _sauvegarder_zone_sur_disque(zone_layer, chemin_tmp)

    return chemin_tmp


def _obtenir_groupe_export(nom_groupe: str) -> QgsLayerTreeGroup:
    """
    Retourne le groupe de calques dedie a cet export, en le creant en
    haut de l'arbre des couches s'il n'existe pas encore.

    Les couches decoupees sont toujours rangees ici plutot que dans le
    groupe actuellement selectionne dans le panneau des couches.
    """

    racine = QgsProject.instance().layerTreeRoot()
    groupe = racine.findGroup(nom_groupe)

    if groupe is None:
        groupe = racine.insertGroup(0, nom_groupe)

    return groupe


# DECOUPAGE
import tempfile  

def decouper_couches_par_zone(zone_etude, chemin_gpkg, layer_ids=None, options=None, parent=None, zone_layer_export=None):
    """
    Decoupe les couches selectionnees selon la zone d'etude et les
    enregistre dans un GeoPackage. Les couches resultantes sont ensuite
    chargees dans QGIS, regroupees dans un groupe dedie a cet export.
    """

    if options is None:
        options = {}

    resolution_wms = float(str(options.get("resolution_wms", 1.0)).replace(",", "."))
    pyramides_raster = bool(options.get("pyramides_raster", True))

    # Résolution demandée par l'utilisateur pour les rasters classiques.
    # Si l'interface ne fournit pas une option spécifique, on réutilise resolution_wms.
    resolution_raster_classique = float(
        str(options.get("resolution_raster_classique", resolution_wms)).replace(",", ".")
    )

    # Sécurité interne pour les rasters fichiers classiques.
    max_pixels_raster_classique = int(
        options.get("max_pixels_raster_classique", 50_000_000)
    )
    # Sécurité interne pour les WMS.
    # Pas besoin de modifier l'interface.
    max_pixels_wms = int(
        options.get("max_pixels_wms", max_pixels_raster_classique)
    )


    # buffer utilisé pour le découpage, en mètres
    buffer_decoupage_m = float(options.get("buffer_decoupage_m", 10.0))

    print("\nOptions export :")
    print(f"  Résolution WMS     : {resolution_wms} m")
    print(f"  Résolution raster classique : {resolution_raster_classique} m")
    print(f"  Pyramides raster   : {'oui' if pyramides_raster else 'non'}")
    print(f"  Max pixels raster classique : {max_pixels_raster_classique:,}")
    print(f"  Max pixels WMS     : {max_pixels_wms:,}")
    print(f"  Buffer decoupage   : {buffer_decoupage_m} m")


    # Chemin de sortie reçu depuis l'interface du plugin
    if not chemin_gpkg:
        QMessageBox.warning(
            parent,
            "Fichier de sortie manquant",
            "Aucun fichier GeoPackage de sortie n'a été défini."
        )
        return

    if not chemin_gpkg.lower().endswith(".gpkg"):
        chemin_gpkg += ".gpkg"

    dossier_sortie = os.path.dirname(chemin_gpkg)

    if dossier_sortie and not os.path.exists(dossier_sortie):
        os.makedirs(dossier_sortie)

    print(f"\nFichier de sortie : {chemin_gpkg}")
        # Nettoyage ancien GeoPackage si meme nom
    if os.path.exists(chemin_gpkg):
        print("Ancien GeoPackage detecte, suppression avant nouvel export...")

        if not _supprimer_ancien_gpkg_si_existe(chemin_gpkg):
            QMessageBox.critical(
                parent,
                "GeoPackage verrouille",
                f"Impossible de supprimer l'ancien GeoPackage :\n\n{chemin_gpkg}\n\n"
                f"Fermez les anciennes couches du resultat dans QGIS ou redemarrez QGIS."
            )
            return

    # Couches sélectionnées dans l'interface du plugin
    couches = []

    if layer_ids:
        projet = QgsProject.instance()

        for layer_id in layer_ids:
            layer = projet.mapLayer(layer_id)

            if layer is not None and layer.name() != "zone_etude":
                couches.append(layer)

    if not couches:
        QMessageBox.warning(
            parent,
            "Aucune couche",
            "Aucune couche sélectionnée pour le découpage."
        )
        return

    # Resolution WMS si necessaire
    a_des_wms = any(
        layer.type() == QgsMapLayer.RasterLayer
        and layer.dataProvider().name() == 'wms'
        for layer in couches
    )
    if a_des_wms:
        print(f"Résolution WMS choisie : {resolution_wms} m")


    # Masque zone cree UNE SEULE FOIS en EPSG:2154
    # Fichier temporaire système (pas dans le dossier de sortie)
    fd_zone, chemin_zone_tmp = tempfile.mkstemp(suffix="_zone.gpkg")
    os.close(fd_zone)
    zone_pour_masque = zone_etude.enregistrerDansScr(QgsCoordinateReferenceSystem("EPSG:2154"))

    zone_buffer_decoupage_2154 = _creer_buffer_decoupage(
        zone_pour_masque,
        buffer_decoupage_m
    )
    _sauvegarder_zone_sur_disque(zone_buffer_decoupage_2154, chemin_zone_tmp)

    # Progression
    progress = QProgressDialog("Decoupage en cours...", "Annuler", 0, len(couches) + 1)
    progress.setWindowModality(QT_WINDOW_MODAL)
    progress.show()

    couches_decoupees = []
    ignores           = []
    erreurs           = []
            # Enregistrer la zone d'etude dans le GeoPackage final
    # Enregistrer la couche zone_etude affichee dans QGIS
    couches_zone = QgsProject.instance().mapLayersByName("zone_etude")

    if couches_zone:
        zone_a_enregistrer = couches_zone[0]
        print("Couche zone_etude trouvee dans QGIS")
        print("Champs zone_etude :", [f.name() for f in zone_a_enregistrer.fields()])
    else:
        zone_a_enregistrer = zone_pour_masque
        print("ATTENTION : couche zone_etude introuvable, utilisation du masque sans attributs")

    if _sauvegarder_zone_dans_gpkg(zone_a_enregistrer, chemin_gpkg):
        layer_zone_finale = QgsVectorLayer(
            f"{chemin_gpkg}|layername=zone_etude",
            "zone_etude",
            "ogr"
        )

        if layer_zone_finale.isValid():
            couches_decoupees.append(layer_zone_finale)
            print("Zone d'etude ajoutee aux couches finales")
        else:
            erreurs.append("zone_etude : couche invalide apres enregistrement")
    else:
        erreurs.append("zone_etude : enregistrement echoue")


    # Le finally garantit le nettoyage du masque meme en cas d'erreur
    try:

        # Boucle couches QGIS
        for i, layer in enumerate(couches):

            progress.setValue(i)
            progress.setLabelText(f"Decoupage : {layer.name()}")

            if progress.wasCanceled():
                print("Annule par l'utilisateur")
                break

            nom_layer = layer.name().replace(" ", "_")
            print(f"\n--- {layer.name()} ---")
            print(f"  Type     : {'Vecteur' if layer.type() == QgsMapLayer.VectorLayer else 'Raster'}")
            print(f"  SCR      : {layer.crs().authid()}")
            print(f"  Provider : {layer.dataProvider().name()}")

            try:
                zone_dans_bon_scr = _reprojeter_masque_decoupage(
                        zone_buffer_decoupage_2154,
                        layer.crs()
                    )

                # VECTEUR
                if layer.type() == QgsMapLayer.VectorLayer:
            
                    nb_entites_total = layer.featureCount()
                    print(f"  Entites totales : {nb_entites_total}")
                    """
                    if nb_entites_total > 500_000:
                        reponse = QMessageBox.question(
                            None,
                            "Couche tres grande",
                            f"La couche contient {nb_entites_total:,} entites\n"
                            f"Le decoupage peut etre tres long.\n\n"
                            f"Continuer quand meme ?",
                            QMessageBox.Yes | QMessageBox.No
                        )
                        if reponse == QMessageBox.No:
                            print("  Clip annule par l'utilisateur")
                            ignores.append(f"{layer.name()} : annule par l'utilisateur")
                            continue
                    """

                    resultat = processing.run(
                        "native:clip",
                        {
                            'INPUT'  : layer,
                            'OVERLAY': zone_dans_bon_scr,
                            'OUTPUT' : 'memory:'
                        }
                    )
                    couche_tmp = resultat['OUTPUT']
                    nb_entites = couche_tmp.featureCount()
                    print(f"  Entites apres clip : {nb_entites}")

                    if nb_entites == 0:
                        ignores.append(f"{layer.name()} : aucune entite dans la zone")
                        continue

                    save_options = QgsVectorFileWriter.SaveVectorOptions()
                    save_options.driverName = "GPKG"
                    save_options.layerName = nom_layer
                    save_options.actionOnExistingFile = (
                        QgsVectorFileWriter.CreateOrOverwriteLayer
                        if os.path.exists(chemin_gpkg)
                        else QgsVectorFileWriter.CreateOrOverwriteFile
                    )

                    QgsVectorFileWriter.writeAsVectorFormatV3(
                        couche_tmp,
                        chemin_gpkg,
                        QgsCoordinateTransformContext(),
                        save_options
                    )

                    layer_decoupee = QgsVectorLayer(
                        f"{chemin_gpkg}|layername={nom_layer}",
                        f"{nom_layer}_clip",
                        "ogr"
                    )

                    if layer_decoupee.isValid():
                        couches_decoupees.append(layer_decoupee)
                        _copier_style_vers_gpkg(layer, layer_decoupee) 
                        print(f"  Vecteur OK")
                    else:
                        erreurs.append(f"{layer.name()} : couche vecteur invalide")

                # VECTEUR TUILE PLAN IGN

                elif _est_vecteur_tuile(layer):

                    print("  Couche vecteur tuile détectée")
                    print("  Export du rendu Plan IGN en raster GeoTIFF")

                    crs_plan_ign = QgsCoordinateReferenceSystem("EPSG:3857")

                    zone_plan_ign_scr = _reprojeter_masque_decoupage(
                        zone_buffer_decoupage_2154,
                        crs_plan_ign
                    )

                    chemin_zone_ign_tmp = None

                    fd_zone_ign, chemin_zone_ign_tmp = tempfile.mkstemp(
                        suffix="_zone_plan_ign.gpkg"
                    )
                    os.close(fd_zone_ign)

                    if os.path.exists(chemin_zone_ign_tmp):
                        os.remove(chemin_zone_ign_tmp)

                    _sauvegarder_zone_sur_disque(
                        zone_plan_ign_scr,
                        chemin_zone_ign_tmp
                    )

                    fd_rendu, chemin_rendu_tmp = tempfile.mkstemp(
                        suffix="_plan_ign_vecteur_tuile.tif",
                        prefix=f"{nom_layer}_"
                    )
                    os.close(fd_rendu)

                    fd_clip, chemin_raster_tmp = tempfile.mkstemp(
                        suffix="_plan_ign_vecteur_tuile_clip.tif",
                        prefix=f"{nom_layer}_"
                    )
                    os.close(fd_clip)

                    if os.path.exists(chemin_rendu_tmp):
                        os.remove(chemin_rendu_tmp)

                    if os.path.exists(chemin_raster_tmp):
                        os.remove(chemin_raster_tmp)

                    try:
                        bbox = zone_plan_ign_scr.extent()

                        print(f"  SCR Plan IGN conservé : {crs_plan_ign.authid()}")
                        print(f"  BBOX Plan IGN : {bbox.toString()}")


                        succes_export = _exporter_vecteur_tuile_plan_ign_en_tif(
                            layer,
                            bbox,
                            crs_plan_ign,
                            chemin_rendu_tmp,
                            parent
                        )

                        if not succes_export or not os.path.exists(chemin_rendu_tmp):
                            erreurs.append(f"{layer.name()} : export vecteur tuile échoué")
                            continue

                        succes_clip = _clipper_raster_avec_gdalwarp(
                            chemin_rendu_tmp,
                            chemin_zone_ign_tmp,
                            chemin_raster_tmp
                        )
                        if succes_clip and os.path.exists(chemin_raster_tmp):
                            _forcer_scr_raster(chemin_raster_tmp, "EPSG:3857")

                        if not succes_clip or not os.path.exists(chemin_raster_tmp):
                            erreurs.append(f"{layer.name()} : clip vecteur tuile échoué")
                            continue

                        print(f"  Taille raster Plan IGN : {os.path.getsize(chemin_raster_tmp)} bytes")

                        succes = _integrer_raster_dans_gpkg(
                            chemin_raster_tmp,
                            chemin_gpkg,
                            nom_layer,
                            generer_overviews=pyramides_raster
                        )

                        if succes:
                            uri_raster = f"GPKG:{chemin_gpkg}:{nom_layer}"
                            layer_decoupee = QgsRasterLayer(
                                uri_raster,
                                f"{nom_layer}_clip"
                            )

                            if layer_decoupee.isValid():
                                couches_decoupees.append(layer_decoupee)
                                print("  Vecteur tuile Plan IGN OK dans GeoPackage")
                                print(f"  SCR conservé : {layer_decoupee.crs().authid()}")
                            else:
                                erreurs.append(
                                    f"{layer.name()} : raster Plan IGN invalide dans GeoPackage"
                                )
                        else:
                            erreurs.append(
                                f"{layer.name()} : intégration GeoPackage Plan IGN échouée"
                            )

                    finally:
                        if chemin_zone_ign_tmp and os.path.exists(chemin_zone_ign_tmp):
                            os.remove(chemin_zone_ign_tmp)
                            print("  Masque Plan IGN temporaire supprimé")

                        '''if os.path.exists(chemin_rendu_tmp):
                            os.remove(chemin_rendu_tmp)
                            print("  Rendu vecteur tuile temporaire supprimé")

                        if os.path.exists(chemin_raster_tmp):
                            os.remove(chemin_raster_tmp)
                            print("  Raster vecteur tuile temporaire supprimé")'''
                        print(f"  DEBUG rendu Plan IGN conserve : {chemin_rendu_tmp}")
                        print(f"  DEBUG clip Plan IGN conserve  : {chemin_raster_tmp}")

                # RASTER
                elif layer.type() == QgsMapLayer.RasterLayer:

                    # Raster temporaire système (pas dans le dossier de sortie)
                    fd_raster, chemin_raster_tmp = tempfile.mkstemp(suffix="_tmp.tif", prefix=f"{nom_layer}_")
                    os.close(fd_raster)

                    # On supprime le fichier vide cree par mkstemp.
                    # GDAL recreera le fichier proprement.
                    if os.path.exists(chemin_raster_tmp):
                        os.remove(chemin_raster_tmp)


                    # Nettoyage garanti du raster temporaire
                    try:
                        provider          = layer.dataProvider().name()
                        nb_bandes_src     = layer.bandCount()

                        print(f"  Bandes source : {nb_bandes_src}")

                        # CAS 1 : WMS → exporter d'abord
                        if provider == 'wms':
                            print(f"  Flux WMS detecte : export en .tif sur la zone")

                            bbox = zone_dans_bon_scr.extent()

                            calcul_resolution_wms = _calculer_resolution_wms_securisee(
                                bbox=bbox,
                                resolution_utilisateur=resolution_wms,
                                max_pixels=max_pixels_wms
                            )

                            resolution_wms_finale = calcul_resolution_wms["resolution_finale"]

                            print(f"  Resolution WMS utilisateur : {calcul_resolution_wms['resolution_utilisateur']:.4f} unite/px")
                            print(
                                f"  Taille WMS avec resolution utilisateur : "
                                f"{calcul_resolution_wms['nb_cols_utilisateur']}x{calcul_resolution_wms['nb_rows_utilisateur']} px "
                                f"({calcul_resolution_wms['nb_pixels_utilisateur']:,} pixels)"
                            )

                            if calcul_resolution_wms["resolution_trop_fine_site"]:
                                message = (
                                    f"La resolution WMS choisie ({calcul_resolution_wms['resolution_utilisateur']:.2f} m/px) "
                                    f"est trop fine pour cette zone d'etude.\n\n"
                                    f"Taille estimee avec cette resolution :\n"
                                    f"{calcul_resolution_wms['nb_cols_utilisateur']} x {calcul_resolution_wms['nb_rows_utilisateur']} px\n"
                                    f"Soit environ {calcul_resolution_wms['nb_pixels_utilisateur'] / 1_000_000:.1f} millions de pixels.\n\n"
                                    f"Limite de securite : {max_pixels_wms / 1_000_000:.0f} millions de pixels.\n\n"
                                    f"Resolution conseillee : {resolution_wms_finale:.2f} m/px\n"
                                    f"Taille estimee avec cette resolution :\n"
                                    f"{calcul_resolution_wms['nb_cols_final']} x {calcul_resolution_wms['nb_rows_final']} px\n"
                                    f"Soit environ {calcul_resolution_wms['nb_pixels_final'] / 1_000_000:.1f} millions de pixels.\n\n"
                                    f"Voulez-vous continuer automatiquement avec la resolution conseillee ?\n\n"
                                    f"Oui : continuer avec {resolution_wms_finale:.2f} m/px\n"
                                    f"Non : annuler pour modifier la resolution et relancer le decoupage"
                                )

                                reponse = QMessageBox.question(
                                    parent,
                                    "Resolution WMS trop fine",
                                    message,
                                    QMessageBox.Yes | QMessageBox.No,
                                    QMessageBox.No
                                )

                                if reponse == QMessageBox.No:
                                    print("  Decoupage annule : resolution WMS utilisateur trop fine")
                                    ignores.append(
                                        f"{layer.name()} : resolution WMS {calcul_resolution_wms['resolution_utilisateur']:.2f} m trop fine, "
                                        f"resolution conseillee {resolution_wms_finale:.2f} m"
                                    )

                                    try:
                                        progress.close()
                                    except Exception:
                                        pass

                                    return

                                print(
                                    f"  Utilisateur accepte la resolution WMS conseillee : "
                                    f"{resolution_wms_finale:.4f} unite/px"
                                )

                            else:
                                print(
                                    f"  Taille WMS estimee acceptable : "
                                    f"{calcul_resolution_wms['nb_cols_final']}x{calcul_resolution_wms['nb_rows_final']} px "
                                    f"({calcul_resolution_wms['nb_pixels_final']:,} pixels)"
                                )

                            succes_export = _exporter_wms_en_tif(
                                layer,
                                bbox,
                                layer.crs(),
                                chemin_raster_tmp,
                                resolution=resolution_wms_finale,
                                parent=parent
                            )

                            if not succes_export or not os.path.exists(chemin_raster_tmp):
                                erreurs.append(f"{layer.name()} : export WMS echoue")
                                continue


                        # CAS 2 : Raster fichier → clip avec gdalwarp
                        else:
                            chemin_source = layer.dataProvider().dataSourceUri()

                            if '|' in chemin_source:
                                chemin_source = chemin_source.split('|')[0]

                            print(f"  Source fichier : {chemin_source}")

                            infos_source = _infos_raster(chemin_source)

                            if not infos_source["valid"]:
                                erreurs.append(f"{layer.name()} : raster source invalide")
                                continue

                            bbox = zone_dans_bon_scr.extent()

                            calcul_resolution = _calculer_resolution_raster_securisee(
                                bbox=bbox,
                                res_x_native=infos_source["res_x"],
                                res_y_native=infos_source["res_y"],
                                resolution_utilisateur=resolution_raster_classique,
                                max_pixels=max_pixels_raster_classique
                            )

                            resolution_finale = calcul_resolution["resolution_finale"]

                            print(f"  Resolution utilisateur : {calcul_resolution['resolution_utilisateur']:.4f} unite/px")
                            print(f"  Resolution native      : {calcul_resolution['resolution_native']:.4f} unite/px")
                            print(
                                f"  Taille avec resolution utilisateur : "
                                f"{calcul_resolution['nb_cols_utilisateur']}x{calcul_resolution['nb_rows_utilisateur']} px "
                                f"({calcul_resolution['nb_pixels_utilisateur']:,} pixels)"
                            )

                            # Message si la résolution demandée est trop fine pour la taille du site
                            if calcul_resolution["resolution_trop_fine_site"]:
                                message = (
                                    f"La resolution choisie ({calcul_resolution['resolution_utilisateur']:.2f} m/px) "
                                    f"est trop fine pour cette zone d'etude.\n\n"
                                    f"Taille estimee avec cette resolution :\n"
                                    f"{calcul_resolution['nb_cols_utilisateur']} x {calcul_resolution['nb_rows_utilisateur']} px\n"
                                    f"Soit environ {calcul_resolution['nb_pixels_utilisateur'] / 1_000_000:.1f} millions de pixels.\n\n"
                                    f"Limite de securite : {max_pixels_raster_classique / 1_000_000:.0f} millions de pixels.\n\n"
                                    f"Resolution conseillee : {resolution_finale:.2f} m/px\n"
                                    f"Taille estimee avec cette resolution :\n"
                                    f"{calcul_resolution['nb_cols_final']} x {calcul_resolution['nb_rows_final']} px\n"
                                    f"Soit environ {calcul_resolution['nb_pixels_final'] / 1_000_000:.1f} millions de pixels.\n\n"
                                    f"Voulez-vous continuer automatiquement avec la resolution conseillee ?\n\n"
                                    f"Oui : continuer avec {resolution_finale:.2f} m/px\n"
                                    f"Non : annuler pour modifier la resolution et relancer le decoupage"
                                )

                                reponse = QMessageBox.question(
                                    parent,
                                    "Resolution trop fine",
                                    message,
                                    QMessageBox.Yes | QMessageBox.No,
                                    QMessageBox.No
                                )

                                if reponse == QMessageBox.No:
                                    print("  Decoupage annule : resolution utilisateur trop fine")
                                    ignores.append(
                                        f"{layer.name()} : resolution {calcul_resolution['resolution_utilisateur']:.2f} m trop fine, "
                                        f"resolution conseillee {resolution_finale:.2f} m"
                                    )

                                    try:
                                        progress.close()
                                    except Exception:
                                        pass

                                    return

                                print(
                                    f"  Utilisateur accepte la resolution conseillee : "
                                    f"{resolution_finale:.4f} unite/px"
                                )

                            elif calcul_resolution["resolution_plus_fine_que_native"]:
                                QMessageBox.information(
                                    parent,
                                    "Resolution ajustee",
                                    f"La resolution choisie ({calcul_resolution['resolution_utilisateur']:.2f} m/px) "
                                    f"est plus fine que la resolution native du raster "
                                    f"({calcul_resolution['resolution_native']:.2f} m/px).\n\n"
                                    f"Le raster sera exporte avec la resolution native : "
                                    f"{resolution_finale:.2f} m/px."
                                )

                                print(
                                    f"  Resolution utilisateur plus fine que native. "
                                    f"Resolution appliquee : {resolution_finale:.4f} unite/px"
                                )

                            else:
                                print(
                                    f"  Taille estimee acceptable : "
                                    f"{calcul_resolution['nb_cols_final']}x{calcul_resolution['nb_rows_final']} px "
                                    f"({calcul_resolution['nb_pixels_final']:,} pixels)"
                                )

                            succes_clip = _clipper_raster_avec_gdalwarp(
                                chemin_source,
                                chemin_zone_tmp,
                                chemin_raster_tmp,
                                resolution=resolution_finale
                            )

                            if not succes_clip or not os.path.exists(chemin_raster_tmp):
                                erreurs.append(f"{layer.name()} : clip raster echoue")
                                continue

                        print(f"  Taille tmp.tif : {os.path.getsize(chemin_raster_tmp)} bytes")

                        succes = _integrer_raster_dans_gpkg(
                            chemin_raster_tmp,
                            chemin_gpkg,
                            nom_layer,
                            generer_overviews=pyramides_raster
                        )

                        if succes:
                            uri_raster = f"GPKG:{chemin_gpkg}:{nom_layer}"
                            layer_decoupee = QgsRasterLayer(uri_raster, f"{nom_layer}_clip")

                            print(f"  Bandes dans GeoPackage : {layer_decoupee.bandCount()}")

                            if layer_decoupee.isValid():
                                couches_decoupees.append(layer_decoupee)
                                print(f"  Raster OK dans GeoPackage")
                            else:
                                erreurs.append(f"{layer.name()} : raster invalide dans GeoPackage")
                        else:
                            erreurs.append(f"{layer.name()} : integration GeoPackage echouee")

                    # Nettoyage du raster temporaire
                    finally:
                        if os.path.exists(chemin_raster_tmp):
                            os.remove(chemin_raster_tmp)
                            print(f"  Raster temporaire supprime")

            except Exception as e:
                erreurs.append(f"{layer.name()} : {str(e)}")
                print(f"ERREUR sur {layer.name()} : {e}")

    # Nettoyage du masque zone temporaire
    finally:
        if os.path.exists(chemin_zone_tmp):
            os.remove(chemin_zone_tmp)
            print("  Masque zone supprime")

    # Afficher les couches dans un groupe dedie, independant des autres
    # groupes du projet (sinon QGIS les depose dans le groupe actuellement
    # selectionne dans le panneau des couches, ce qui les eparpille).
    nom_groupe_export = os.path.splitext(os.path.basename(chemin_gpkg))[0]
    groupe_export = _obtenir_groupe_export(nom_groupe_export)

    for layer_decoupee in couches_decoupees:
        QgsProject.instance().addMapLayer(layer_decoupee, False)
        groupe_export.addLayer(layer_decoupee)

    # Rapport
    msg = f"{len(couches_decoupees)} couche(s) decoupee(s) avec succes\n"
    msg += f"GeoPackage : {chemin_gpkg}\n"

    if ignores:
        msg += f"\n{len(ignores)} couche(s) sans donnees dans la zone :\n"
        msg += "\n".join(ignores)

    if erreurs:
        msg += f"\n\n{len(erreurs)} erreur(s) :\n"
        msg += "\n".join(erreurs)

    QMessageBox.information(None, "Decoupage termine", msg)
    print(msg)