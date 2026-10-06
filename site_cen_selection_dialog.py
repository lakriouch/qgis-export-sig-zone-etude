from .zone_etude import ZoneEtude
from .compat import ROLE_CODESITEP, ROLE_NOMSITEP, ROLE_COMMUNES

# ─────────────────────────────────────────────
#  FONCTION BDD 
# ─────────────────────────────────────────────
def charger_zone_bdd(codesitep: str, nomsitep: str, communes: str, pg_service_path: str):
    """
    Équivalent 'synchrone' de OutilDessinPolygone.
    Crée un ZoneEtude depuis la base et lance le découpage.
    """
    import os

    try:
        import psycopg2
    except ImportError:
        print("ERREUR - psycopg2 non disponible")
        return False

    if os.path.exists(pg_service_path):
        os.environ['PGSERVICEFILE'] = pg_service_path

    try:
        conn = psycopg2.connect(service='bd CEN (admin)')
        cur = conn.cursor()

        # ─────────────────────────────────────────────
        # - Récupère le site demandé dans site_cen
        # - Cherche sa géométrie directe dans geo_site
        # - Cherche aussi les géométries des sous-sites
        #   qui ont ce site comme code_site_mere
        # - Si des sous-sites existent, on utilise leur union
        # - Sinon, on utilise la géométrie directe du site
        # ─────────────────────────────────────────────
        cur.execute("""
            WITH site_selectionne AS (
                SELECT *
                FROM bd_site_cen.site_cen
                WHERE codesitep = %s
            ),

            geom_directe AS (
                SELECT 
                    codesitep,
                    ST_Union(geom) AS geom
                FROM bd_site_cen.geo_site
                WHERE codesitep = %s
                GROUP BY codesitep
            ),

            geom_sous_sites AS (
                SELECT 
                    ss.code_site_mere AS codesitep,
                    ST_Union(g.geom) AS geom
                FROM bd_site_cen.site_cen ss
                JOIN bd_site_cen.geo_site g
                    ON ss.codesitep = g.codesitep
                WHERE ss.code_site_mere = %s
                GROUP BY ss.code_site_mere
            )

            SELECT 
                s.*,
                ST_AsText(COALESCE(gs.geom, gd.geom)) AS geom_wkt,
                ST_SRID(COALESCE(gs.geom, gd.geom)) AS srid
            FROM site_selectionne s
            LEFT JOIN geom_directe gd
                ON s.codesitep = gd.codesitep
            LEFT JOIN geom_sous_sites gs
                ON s.codesitep = gs.codesitep
        """, (codesitep, codesitep, codesitep))

        # Récupère les noms des colonnes retournées par la requête
        col_names = [desc[0] for desc in cur.description]

        # Récupère la ligne du site sélectionné
        row = cur.fetchone()

        cur.close()
        conn.close()

        if not row:
            print("ERREUR - Site introuvable")
            return False

       
        data = dict(zip(col_names, row))

        geom_wkt = data.pop("geom_wkt")

        srid = data.pop("srid")

        if not geom_wkt:
            print("ERREUR - Site trouvé mais aucune géométrie disponible")
            return False

        # Récupère les champs principaux
        # Si un champ est absent, on garde la valeur passée en paramètre
        codesitep_db = data.pop("codesitep", codesitep)
        nomsitep_db = data.pop("nomsitep", nomsitep)
        communes_db = data.pop("communes", communes)

        # Convertit la géométrie WKT en géométrie QGIS
        geom = QgsGeometry.fromWkt(geom_wkt)

        if geom.isEmpty():
            print("ERREUR - Géométrie invalide")
            return False

        attributs = data

        # ─────────────────────────────────────────────
        # Crée la zone d'étude avec la géométrie récupérée
        # ─────────────────────────────────────────────
        zone = ZoneEtude.depuisSiteCEN(
            geom,
            codesitep_db,
            nomsitep_db,
            communes_db,
            attributs=attributs
        )

        zone.enregistrerCommeCouche()

        print(f"Source     : {zone.getSource()}")
        print(f"Site       : {zone.getNomSite()} ({zone.getCodeSite()})")
        print(f"Attributs  : {list(attributs.keys())}")
        print(f"BoundingBox: {zone.getBoundingBox()}")

        return zone

    except Exception as e:
        print(f"ERREUR - Chargement BDD : {e}")
        import traceback
        traceback.print_exc()
        return None


#ui 
from qgis.PyQt.QtWidgets import (QDialog, QVBoxLayout, QLineEdit, QListWidget, 
                                  QListWidgetItem, QPushButton, QHBoxLayout, QLabel)
from qgis.PyQt.QtCore import Qt
import os
import psycopg2
from qgis.core import QgsGeometry


class SelecteurSiteCEN(QDialog):
    
    def __init__(self, pg_service_path, pg_service_name='bd CEN (admin)', parent=None):
        super().__init__(parent)
        self.setWindowTitle("Sélectionner un site CEN")
        self.resize(450, 500)
        
        self.pg_service_path = pg_service_path
        self.pg_service_name = pg_service_name
        self._all_sites = []
        self.selected_codesitep = None
        self.selected_nomsitep = None
        self.selected_communes = None

        # ─── UI ───
        layout = QVBoxLayout(self)
        
        self.label = QLabel("Chargement...")
        layout.addWidget(self.label)
        
        self.lineEdit = QLineEdit()
        self.lineEdit.setPlaceholderText("Tapez 3 lettres minimum...")
        layout.addWidget(self.lineEdit)
        
        self.listWidget = QListWidget()
        layout.addWidget(self.listWidget)
        
        btn_layout = QHBoxLayout()
        self.btnChoisir = QPushButton("Choisir ce site")
        self.btnChoisir.setEnabled(False)
        self.btnAnnuler = QPushButton("Annuler")
        btn_layout.addWidget(self.btnChoisir)
        btn_layout.addWidget(self.btnAnnuler)
        layout.addLayout(btn_layout)
        
        # ─── Connexions ───
        self.lineEdit.textChanged.connect(self._filtrer)
        self.listWidget.itemClicked.connect(self._selectionner)
        self.listWidget.itemDoubleClicked.connect(self._valider)
        self.btnChoisir.clicked.connect(self._valider)
        self.btnAnnuler.clicked.connect(self.reject)
        
        # ─── Chargement BDD ───
        self._charger_tous_les_sites()
    
    def _charger_tous_les_sites(self):
        try:
            if os.path.exists(self.pg_service_path):
                os.environ['PGSERVICEFILE'] = self.pg_service_path
            
            conn = psycopg2.connect(service=self.pg_service_name)
            cur = conn.cursor()
            cur.execute("""
                SELECT codesitep, nomsitep, communes
                FROM bd_site_cen.site_cen
                ORDER BY nomsitep ASC
            """)
            self._all_sites = cur.fetchall()
            cur.close()
            conn.close()
            self.label.setText(f"{len(self._all_sites)} sites. Tapez les 3 premières lettres.")
        except Exception as e:
            self.label.setText(f"ERREUR BDD : {e}")


    def _normaliser_texte(self, texte):
        """
        Normalise un texte pour la recherche :
        - remplace None par une chaîne vide
        - met en minuscules
        - supprime les accents
        """
        import unicodedata

        if texte is None:
            return ""

        texte = str(texte).strip().lower()

        texte = unicodedata.normalize("NFD", texte)

        texte = "".join(
            caractere for caractere in texte
            if unicodedata.category(caractere) != "Mn"
        )

        return texte

    def _filtrer(self, texte):
        self.listWidget.clear()
        self.btnChoisir.setEnabled(False)

        self.selected_codesitep = None
        self.selected_nomsitep = None
        self.selected_communes = None

    
        texte = self._normaliser_texte(texte)

        compteur = 0

        for codesitep, nomsitep, communes in self._all_sites:
            nomsitep_txt = nomsitep or ""
            communes_txt = communes or ""

            
            contenu = self._normaliser_texte(f"{nomsitep_txt} {communes_txt}")


            if texte == "" or texte in contenu:

                if communes_txt:
                    libelle = f"{nomsitep_txt} — {communes_txt}"
                else:
                    libelle = nomsitep_txt

                item = QListWidgetItem(libelle)

                item.setData(ROLE_CODESITEP, codesitep)
                item.setData(ROLE_NOMSITEP, nomsitep_txt)
                item.setData(ROLE_COMMUNES, communes_txt)

                self.listWidget.addItem(item)
                compteur += 1

        self.label.setText(f"{compteur} site(s) trouvé(s)")


    def _selectionner(self, item):
        self.selected_codesitep = item.data(ROLE_CODESITEP)
        self.selected_nomsitep = item.data(ROLE_NOMSITEP)
        self.selected_communes = item.data(ROLE_COMMUNES)


        self.btnChoisir.setEnabled(True)

    
    def _valider(self):
        """
        Valide seulement le site sélectionné.
        """

        item = self.listWidget.currentItem()

        if item is not None:
            self.selected_codesitep = item.data(ROLE_CODESITEP)
            self.selected_nomsitep = item.data(ROLE_NOMSITEP)
            self.selected_communes = item.data(ROLE_COMMUNES)


        if not self.selected_codesitep:
            return

        self.accept()
