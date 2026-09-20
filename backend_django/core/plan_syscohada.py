"""Compatibilité : utiliser apps.comptabilite.plan_syscohada dans le nouveau code."""
import sys
from importlib import import_module
sys.modules[__name__] = import_module("apps.comptabilite.plan_syscohada")
