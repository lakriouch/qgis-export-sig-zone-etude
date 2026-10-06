import datetime
from decimal import Decimal

from qgis.core import (
    QgsProject,
    QgsGeometry,
    QgsFeature,
    QgsVectorLayer,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
)
class ZoneEtude:

    def __init__(self, geometrie: QgsGeometry, source: str):
        self._geometrie = geometrie
        self._source = source
        self._codesitep = None
        self._nomsitep = None
        self._communes = None
        self._attributs = {}

    @staticmethod
    def depuisDessin(geometrie: QgsGeometry) -> "ZoneEtude":
        if geometrie is None or geometrie.isEmpty():
            raise ValueError("La geometrie dessinee est vide")
        return ZoneEtude(geometrie, source="dessin")

    @staticmethod
    def depuisSiteCEN(
        geometrie: QgsGeometry,
        codesitep: str,
        nomsitep: str,
        communes: str = None,
        attributs: dict = None
    ) -> "ZoneEtude":
        if geometrie is None or geometrie.isEmpty():
            raise ValueError("La geometrie du site CEN est vide")

        zone = ZoneEtude(geometrie, source="bdd")
        zone._codesitep = codesitep
        zone._nomsitep = nomsitep
        zone._communes = communes
        zone._attributs = attributs or {}
        return zone

    def getGeometrie(self) -> QgsGeometry:
        return self._geometrie

    def getBoundingBox(self):
        return self._geometrie.boundingBox()

    def getSource(self) -> str:
        return self._source

    def getCodeSite(self) -> str:
        return self._codesitep

    def getNomSite(self) -> str:
        return self._nomsitep

    def getCommunes(self) -> str:
        return self._communes

    def enregistrerCommeCouche(self) -> QgsVectorLayer:
        for layer in QgsProject.instance().mapLayers().values():
            if layer.name() == "zone_etude":
                QgsProject.instance().removeMapLayer(layer.id())
                break

        crs_projet = QgsProject.instance().crs()
        if not crs_projet.isValid():
            crs_projet = QgsCoordinateReferenceSystem("EPSG:4326")

        uri = "Polygon"
        uri += "?field=codesitep:string(50)"
        uri += "&field=nomsitep:string(255)"
        uri += "&field=communes:string(255)"

        for nom, valeur in self._attributs.items():
            if valeur is None:
                uri += f"&field={nom}:string(255)"
            elif isinstance(valeur, bool):
                uri += f"&field={nom}:integer"
            elif isinstance(valeur, int):
                uri += f"&field={nom}:integer"
            elif isinstance(valeur, (float, Decimal)):
                uri += f"&field={nom}:double"
            elif isinstance(valeur, datetime.date):
                uri += f"&field={nom}:date"
            else:
                txt = str(valeur)
                lg = max(255, len(txt) + 50)
                uri += f"&field={nom}:string({lg})"

        layer = QgsVectorLayer(uri, "zone_etude", "memory")
        layer.setCrs(crs_projet)

        # Remplissage des attributs
        valeurs = [
            self._codesitep or "",
            self._nomsitep or "",
            self._communes or ""
        ]
        
        for v in self._attributs.values():
            if isinstance(v, bool):
                valeurs.append(1 if v else 0)
            elif isinstance(v, Decimal):
                valeurs.append(float(v))
            else:
                valeurs.append(v if v is not None else None)

        feature = QgsFeature()
        feature.setGeometry(self._geometrie)
        feature.setAttributes(valeurs)

        layer.dataProvider().addFeatures([feature])
        layer.updateExtents()

        QgsProject.instance().addMapLayer(layer)

        print(f"OK - Zone enregistree ({len(self._attributs)} attribut(s)) en {crs_projet.authid() or crs_projet.description()}")

        return layer

    def enregistrerDansScr(
        self,
        crs_cible: QgsCoordinateReferenceSystem
    ) -> QgsVectorLayer:

        crs_source = QgsProject.instance().crs()
        geom_reprojetee = QgsGeometry(self._geometrie)

        if crs_source != crs_cible:
            transform = QgsCoordinateTransform(
                crs_source,
                crs_cible,
                QgsProject.instance()
            )
            geom_reprojetee.transform(transform)

        layer_tmp = QgsVectorLayer("Polygon", "zone_etude_tmp", "memory")
        layer_tmp.setCrs(crs_cible)

        feature = QgsFeature()
        feature.setGeometry(geom_reprojetee)

        layer_tmp.dataProvider().addFeatures([feature])
        layer_tmp.updateExtents()

        return layer_tmp
