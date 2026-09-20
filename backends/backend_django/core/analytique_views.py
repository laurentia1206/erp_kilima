"""Compatibilité : utiliser apps.comptabilite.analytique_views dans le nouveau code."""
import sys
from importlib import import_module
sys.modules[__name__] = import_module("apps.comptabilite.analytique_views")
