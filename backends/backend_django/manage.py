#!/usr/bin/env python
"""Utilitaire de gestion Django — ERP KILIMA HOLDINGS (portage)."""
import os
import sys


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "kilima.settings")
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
