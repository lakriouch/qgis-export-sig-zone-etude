from qgis.core import QgsGeometry, QgsWkbTypes
from qgis.gui import QgsMapToolEmitPoint, QgsRubberBand
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtCore import Qt

from .zone_etude import ZoneEtude
from .compat import QT_RIGHT_BUTTON

class OutilDessinPolygone(QgsMapToolEmitPoint):
    """
    Outil QGIS pour dessiner un polygone.

    Clic gauche : ajoute un point.
    Clic droit  : termine le polygone.

    """

    def __init__(self, canvas, callback_fin_dessin):
        super().__init__(canvas)

        self._canvas = canvas
        self._callback_fin_dessin = callback_fin_dessin
        self._points = []

        self._rubberBand = QgsRubberBand(canvas, QgsWkbTypes.PolygonGeometry)
        self._rubberBand.setColor(QColor(255, 0, 0, 100))
        self._rubberBand.setWidth(2)

    def canvasReleaseEvent(self, event):
        point = self.toMapCoordinates(event.pos())

        if event.button() == QT_RIGHT_BUTTON:

            if len(self._points) < 3:
                print("ERREUR - Minimum 3 points pour un polygone")
                return

            points_polygone = self._points + [self._points[0]]
            geom = QgsGeometry.fromPolygonXY([points_polygone])

            try:
                zone = ZoneEtude.depuisDessin(geom)
                self._callback_fin_dessin(zone)

            except ValueError as e:
                print(f"ERREUR : {e}")

            self.reset()
            return

        self._points.append(point)
        self._rubberBand.addPoint(point)

    def reset(self):
        self._rubberBand.reset(QgsWkbTypes.PolygonGeometry)
        self._points = []
