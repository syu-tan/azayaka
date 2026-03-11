# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

import os
import sys

from azayaka import __version__ as azayaka_version

sys.path.insert(0, os.path.abspath('../../../src'))

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = 'Azayaka'
copyright = '2026, Syusuke Yasui, Yutaka Yamamoto'
author = 'Syusuke Yasui, Yutaka Yamamoto'
release = azayaka_version

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    'sphinx.ext.autodoc', #.  docstrin自動ドキュメント生成
    'sphinx.ext.autosummary',
    'sphinx.ext.napoleon', # Numpyスタイル
    'sphinx.ext.viewcode',
    'myst_parser' # Markdown support
]

templates_path = ['_templates']
exclude_patterns = []

autosummary_generate = True
autodoc_default_options = {
    "members": True,
    "undoc-members": True,
    "private-members": True,
    "special-members": "__init__",
    "show-inheritance": True,
}
napoleon_include_private_with_doc = True
napoleon_include_special_with_doc = True

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = 'sphinx_rtd_theme' # sphinx_rtd_theme, sphinx-book-theme
html_static_path = ['_static']
