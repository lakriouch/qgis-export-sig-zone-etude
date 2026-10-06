# -*- coding: utf-8 -*-
"""
Compatibilité Qt / QGIS pour le plugin Export SIG Zone Etude.

Compatible QGIS 3.x / Qt5 et QGIS 4.x / Qt6.
Dans un plugin QGIS, on importe Qt via qgis.PyQt.
"""

from qgis.PyQt.QtCore import Qt, QT_VERSION_STR
from qgis.PyQt.QtWidgets import QSizePolicy


QT_VERSION_MAJOR = int(QT_VERSION_STR.split(".")[0])


def qt_enum(enum_group_name, enum_name, legacy_owner=Qt):
    """
    Retourne une constante Qt compatible Qt5 / Qt6.

    Qt5 :
        Qt.UserRole
        Qt.RightButton
        Qt.Checked

    Qt6 :
        Qt.ItemDataRole.UserRole
        Qt.MouseButton.RightButton
        Qt.CheckState.Checked
    """
    enum_group = getattr(Qt, enum_group_name, None)

    if enum_group is not None and hasattr(enum_group, enum_name):
        return getattr(enum_group, enum_name)

    return getattr(legacy_owner, enum_name)


def qt_enum_int(enum_group_name, enum_name, legacy_owner=Qt):
    """
    Retourne une constante Qt sous forme d'entier.

    Utile pour les rôles Qt :
        UserRole
        UserRole + 1
        UserRole + 2

    En Qt6, les enums ont souvent un attribut .value.
    """
    value = qt_enum(enum_group_name, enum_name, legacy_owner)

    if hasattr(value, "value"):
        return value.value

    return int(value)


def qsize_policy(policy_name):
    """
    Retourne une constante QSizePolicy compatible Qt5 / Qt6.

    Qt5 :
        QSizePolicy.Preferred

    Qt6 :
        QSizePolicy.Policy.Preferred
    """
    policy_group = getattr(QSizePolicy, "Policy", None)

    if policy_group is not None and hasattr(policy_group, policy_name):
        return getattr(policy_group, policy_name)

    return getattr(QSizePolicy, policy_name)


def exec_dialog(dialog):
    """
    Exécute un QDialog de façon compatible Qt5 / Qt6.
    """
    if hasattr(dialog, "exec"):
        return dialog.exec()

    return dialog.exec_()


# ---------------------------------------------------------------------
# QSizePolicy
# ---------------------------------------------------------------------

QSIZE_POLICY_PREFERRED = qsize_policy("Preferred")
QSIZE_POLICY_EXPANDING = qsize_policy("Expanding")
QSIZE_POLICY_MINIMUM = qsize_policy("Minimum")
QSIZE_POLICY_MAXIMUM = qsize_policy("Maximum")
QSIZE_POLICY_FIXED = qsize_policy("Fixed")
QSIZE_POLICY_IGNORED = qsize_policy("Ignored")
QSIZE_POLICY_MINIMUM_EXPANDING = qsize_policy("MinimumExpanding")


# ---------------------------------------------------------------------
# CheckState
# ---------------------------------------------------------------------

QT_CHECKED = qt_enum("CheckState", "Checked")
QT_UNCHECKED = qt_enum("CheckState", "Unchecked")
QT_PARTIALLY_CHECKED = qt_enum("CheckState", "PartiallyChecked")


# ---------------------------------------------------------------------
# ItemDataRole
# Important : en entier pour pouvoir faire UserRole + 1, + 2, etc.
# ---------------------------------------------------------------------

QT_USER_ROLE = qt_enum_int("ItemDataRole", "UserRole")
QT_DISPLAY_ROLE = qt_enum_int("ItemDataRole", "DisplayRole")
QT_EDIT_ROLE = qt_enum_int("ItemDataRole", "EditRole")
QT_CHECK_STATE_ROLE = qt_enum_int("ItemDataRole", "CheckStateRole")


# Rôles personnalisés pour ton plugin
ROLE_CODESITEP = QT_USER_ROLE
ROLE_NOMSITEP = QT_USER_ROLE + 1
ROLE_COMMUNES = QT_USER_ROLE + 2


# ---------------------------------------------------------------------
# AlignmentFlag
# ---------------------------------------------------------------------

QT_ALIGN_LEFT = qt_enum("AlignmentFlag", "AlignLeft")
QT_ALIGN_RIGHT = qt_enum("AlignmentFlag", "AlignRight")
QT_ALIGN_CENTER = qt_enum("AlignmentFlag", "AlignCenter")


# ---------------------------------------------------------------------
# Orientation
# ---------------------------------------------------------------------

QT_HORIZONTAL = qt_enum("Orientation", "Horizontal")
QT_VERTICAL = qt_enum("Orientation", "Vertical")


# ---------------------------------------------------------------------
# MouseButton
# ---------------------------------------------------------------------

QT_LEFT_BUTTON = qt_enum("MouseButton", "LeftButton")
QT_RIGHT_BUTTON = qt_enum("MouseButton", "RightButton")
QT_MIDDLE_BUTTON = qt_enum("MouseButton", "MiddleButton")


# ---------------------------------------------------------------------
# WindowModality
# ---------------------------------------------------------------------

QT_WINDOW_MODAL = qt_enum("WindowModality", "WindowModal")
QT_APPLICATION_MODAL = qt_enum("WindowModality", "ApplicationModal")


# ---------------------------------------------------------------------
# WindowType / WindowFlags
# ---------------------------------------------------------------------

QT_WINDOW = qt_enum("WindowType", "Window")
QT_WINDOW_MINIMIZE_BUTTON_HINT = qt_enum("WindowType", "WindowMinimizeButtonHint")
QT_WINDOW_MAXIMIZE_BUTTON_HINT = qt_enum("WindowType", "WindowMaximizeButtonHint")
QT_WINDOW_CLOSE_BUTTON_HINT = qt_enum("WindowType", "WindowCloseButtonHint")

from qgis.PyQt.QtWidgets import QDialog

try:
    QDIALOG_ACCEPTED = QDialog.DialogCode.Accepted
    QDIALOG_REJECTED = QDialog.DialogCode.Rejected
except AttributeError:
    QDIALOG_ACCEPTED = QDialog.Accepted
    QDIALOG_REJECTED = QDialog.Rejected
