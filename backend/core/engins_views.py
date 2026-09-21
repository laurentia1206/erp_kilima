"""Compatibilité : utiliser apps.engins.views dans le nouveau code."""
import sys
from importlib import import_module
sys.modules[__name__] = import_module("apps.engins.views")
