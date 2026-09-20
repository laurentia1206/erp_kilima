"""Compatibilité : utiliser apps.maintenance.services dans le nouveau code."""
import sys
from importlib import import_module
sys.modules[__name__] = import_module("apps.maintenance.services")
