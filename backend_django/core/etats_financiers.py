"""Compatibilité : utiliser apps.comptabilite.etats_financiers dans le nouveau code."""
import sys
from importlib import import_module
sys.modules[__name__] = import_module("apps.comptabilite.etats_financiers")
