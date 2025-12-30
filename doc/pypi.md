# PyPI release procedure

This document describes how to build and upload azayaka to PyPI.

## Prerequisites

- Python 3.11+
- Account on PyPI and TestPyPI
- API tokens for PyPI and TestPyPI

Install the tools:

```bash
python -m pip install --upgrade build twine
```

## Build the package

Run from the repository root:

```bash
python -m build
```

Logs:
```log
* Creating isolated environment: venv+pip...
* Installing packages in isolated environment:
  - setuptools>=68
  - wheel
* Getting build dependencies for sdist...
/private/var/folders/vg/3f79b2x54mz7ny6lbm1bfhrw0000gn/T/build-env-6zdd_vaj/lib/python3.11/site-packages/setuptools/config/_apply_pyprojecttoml.py:82: SetuptoolsDeprecationWarning: `project.license` as a TOML table is deprecated
!!

        ********************************************************************************
        Please use a simple string containing a SPDX expression for `project.license`. You can also use `project.license-files`. (Both options available on setuptools>=77.0.0).

        By 2026-Feb-18, you need to update your project and remove deprecated calls
        or your builds will no longer be supported.

        See https://packaging.python.org/en/latest/guides/writing-pyproject-toml/#license for details.
        ********************************************************************************

!!
  corresp(dist, value, root_dir)
/private/var/folders/vg/3f79b2x54mz7ny6lbm1bfhrw0000gn/T/build-env-6zdd_vaj/lib/python3.11/site-packages/setuptools/config/_apply_pyprojecttoml.py:61: SetuptoolsDeprecationWarning: License classifiers are deprecated.
!!

        ********************************************************************************
        Please consider removing the following classifiers in favor of a SPDX license expression:

        License :: OSI Approved :: GNU Affero General Public License v3

        See https://packaging.python.org/en/latest/guides/writing-pyproject-toml/#license for details.
        ********************************************************************************

!!
  dist._finalize_license_expression()
/private/var/folders/vg/3f79b2x54mz7ny6lbm1bfhrw0000gn/T/build-env-6zdd_vaj/lib/python3.11/site-packages/setuptools/dist.py:759: SetuptoolsDeprecationWarning: License classifiers are deprecated.
!!

        ********************************************************************************
        Please consider removing the following classifiers in favor of a SPDX license expression:

        License :: OSI Approved :: GNU Affero General Public License v3

        See https://packaging.python.org/en/latest/guides/writing-pyproject-toml/#license for details.
        ********************************************************************************

!!
  self._finalize_license_expression()
running egg_info
creating src/azayaka.egg-info
writing src/azayaka.egg-info/PKG-INFO
writing dependency_links to src/azayaka.egg-info/dependency_links.txt
writing top-level names to src/azayaka.egg-info/top_level.txt
writing manifest file 'src/azayaka.egg-info/SOURCES.txt'
reading manifest file 'src/azayaka.egg-info/SOURCES.txt'
adding license file 'LICENSE'
writing manifest file 'src/azayaka.egg-info/SOURCES.txt'
* Building sdist...
/private/var/folders/vg/3f79b2x54mz7ny6lbm1bfhrw0000gn/T/build-env-6zdd_vaj/lib/python3.11/site-packages/setuptools/config/_apply_pyprojecttoml.py:82: SetuptoolsDeprecationWarning: `project.license` as a TOML table is deprecated
!!

        ********************************************************************************
        Please use a simple string containing a SPDX expression for `project.license`. You can also use `project.license-files`. (Both options available on setuptools>=77.0.0).

        By 2026-Feb-18, you need to update your project and remove deprecated calls
        or your builds will no longer be supported.

        See https://packaging.python.org/en/latest/guides/writing-pyproject-toml/#license for details.
        ********************************************************************************

!!
  corresp(dist, value, root_dir)
/private/var/folders/vg/3f79b2x54mz7ny6lbm1bfhrw0000gn/T/build-env-6zdd_vaj/lib/python3.11/site-packages/setuptools/config/_apply_pyprojecttoml.py:61: SetuptoolsDeprecationWarning: License classifiers are deprecated.
!!

        ********************************************************************************
        Please consider removing the following classifiers in favor of a SPDX license expression:

        License :: OSI Approved :: GNU Affero General Public License v3

        See https://packaging.python.org/en/latest/guides/writing-pyproject-toml/#license for details.
        ********************************************************************************

!!
  dist._finalize_license_expression()
/private/var/folders/vg/3f79b2x54mz7ny6lbm1bfhrw0000gn/T/build-env-6zdd_vaj/lib/python3.11/site-packages/setuptools/dist.py:759: SetuptoolsDeprecationWarning: License classifiers are deprecated.
!!

        ********************************************************************************
        Please consider removing the following classifiers in favor of a SPDX license expression:

        License :: OSI Approved :: GNU Affero General Public License v3

        See https://packaging.python.org/en/latest/guides/writing-pyproject-toml/#license for details.
        ********************************************************************************

!!
  self._finalize_license_expression()
running sdist
running egg_info
writing src/azayaka.egg-info/PKG-INFO
writing dependency_links to src/azayaka.egg-info/dependency_links.txt
writing top-level names to src/azayaka.egg-info/top_level.txt
reading manifest file 'src/azayaka.egg-info/SOURCES.txt'
adding license file 'LICENSE'
writing manifest file 'src/azayaka.egg-info/SOURCES.txt'
running check
creating azayaka-0.1.0
creating azayaka-0.1.0/src/azayaka
creating azayaka-0.1.0/src/azayaka.egg-info
copying files to azayaka-0.1.0...
copying LICENSE -> azayaka-0.1.0
copying README.md -> azayaka-0.1.0
copying pyproject.toml -> azayaka-0.1.0
copying src/azayaka/__init__.py -> azayaka-0.1.0/src/azayaka
copying src/azayaka.egg-info/PKG-INFO -> azayaka-0.1.0/src/azayaka.egg-info
copying src/azayaka.egg-info/SOURCES.txt -> azayaka-0.1.0/src/azayaka.egg-info
copying src/azayaka.egg-info/dependency_links.txt -> azayaka-0.1.0/src/azayaka.egg-info
copying src/azayaka.egg-info/top_level.txt -> azayaka-0.1.0/src/azayaka.egg-info
copying src/azayaka.egg-info/SOURCES.txt -> azayaka-0.1.0/src/azayaka.egg-info
Writing azayaka-0.1.0/setup.cfg
Creating tar archive
removing 'azayaka-0.1.0' (and everything under it)
* Building wheel from sdist
* Creating isolated environment: venv+pip...
* Installing packages in isolated environment:
  - setuptools>=68
  - wheel
* Getting build dependencies for wheel...
/private/var/folders/vg/3f79b2x54mz7ny6lbm1bfhrw0000gn/T/build-env-8ri2sog9/lib/python3.11/site-packages/setuptools/config/_apply_pyprojecttoml.py:82: SetuptoolsDeprecationWarning: `project.license` as a TOML table is deprecated
!!

        ********************************************************************************
        Please use a simple string containing a SPDX expression for `project.license`. You can also use `project.license-files`. (Both options available on setuptools>=77.0.0).

        By 2026-Feb-18, you need to update your project and remove deprecated calls
        or your builds will no longer be supported.

        See https://packaging.python.org/en/latest/guides/writing-pyproject-toml/#license for details.
        ********************************************************************************

!!
  corresp(dist, value, root_dir)
/private/var/folders/vg/3f79b2x54mz7ny6lbm1bfhrw0000gn/T/build-env-8ri2sog9/lib/python3.11/site-packages/setuptools/config/_apply_pyprojecttoml.py:61: SetuptoolsDeprecationWarning: License classifiers are deprecated.
!!

        ********************************************************************************
        Please consider removing the following classifiers in favor of a SPDX license expression:

        License :: OSI Approved :: GNU Affero General Public License v3

        See https://packaging.python.org/en/latest/guides/writing-pyproject-toml/#license for details.
        ********************************************************************************

!!
  dist._finalize_license_expression()
/private/var/folders/vg/3f79b2x54mz7ny6lbm1bfhrw0000gn/T/build-env-8ri2sog9/lib/python3.11/site-packages/setuptools/dist.py:759: SetuptoolsDeprecationWarning: License classifiers are deprecated.
!!

        ********************************************************************************
        Please consider removing the following classifiers in favor of a SPDX license expression:

        License :: OSI Approved :: GNU Affero General Public License v3

        See https://packaging.python.org/en/latest/guides/writing-pyproject-toml/#license for details.
        ********************************************************************************

!!
  self._finalize_license_expression()
running egg_info
writing src/azayaka.egg-info/PKG-INFO
writing dependency_links to src/azayaka.egg-info/dependency_links.txt
writing top-level names to src/azayaka.egg-info/top_level.txt
reading manifest file 'src/azayaka.egg-info/SOURCES.txt'
adding license file 'LICENSE'
writing manifest file 'src/azayaka.egg-info/SOURCES.txt'
* Building wheel...
/private/var/folders/vg/3f79b2x54mz7ny6lbm1bfhrw0000gn/T/build-env-8ri2sog9/lib/python3.11/site-packages/setuptools/config/_apply_pyprojecttoml.py:82: SetuptoolsDeprecationWarning: `project.license` as a TOML table is deprecated
!!

        ********************************************************************************
        Please use a simple string containing a SPDX expression for `project.license`. You can also use `project.license-files`. (Both options available on setuptools>=77.0.0).

        By 2026-Feb-18, you need to update your project and remove deprecated calls
        or your builds will no longer be supported.

        See https://packaging.python.org/en/latest/guides/writing-pyproject-toml/#license for details.
        ********************************************************************************

!!
  corresp(dist, value, root_dir)
/private/var/folders/vg/3f79b2x54mz7ny6lbm1bfhrw0000gn/T/build-env-8ri2sog9/lib/python3.11/site-packages/setuptools/config/_apply_pyprojecttoml.py:61: SetuptoolsDeprecationWarning: License classifiers are deprecated.
!!

        ********************************************************************************
        Please consider removing the following classifiers in favor of a SPDX license expression:

        License :: OSI Approved :: GNU Affero General Public License v3

        See https://packaging.python.org/en/latest/guides/writing-pyproject-toml/#license for details.
        ********************************************************************************

!!
  dist._finalize_license_expression()
/private/var/folders/vg/3f79b2x54mz7ny6lbm1bfhrw0000gn/T/build-env-8ri2sog9/lib/python3.11/site-packages/setuptools/dist.py:759: SetuptoolsDeprecationWarning: License classifiers are deprecated.
!!

        ********************************************************************************
        Please consider removing the following classifiers in favor of a SPDX license expression:

        License :: OSI Approved :: GNU Affero General Public License v3

        See https://packaging.python.org/en/latest/guides/writing-pyproject-toml/#license for details.
        ********************************************************************************

!!
  self._finalize_license_expression()
running bdist_wheel
running build
running build_py
creating build/lib/azayaka
copying src/azayaka/__init__.py -> build/lib/azayaka
running egg_info
writing src/azayaka.egg-info/PKG-INFO
writing dependency_links to src/azayaka.egg-info/dependency_links.txt
writing top-level names to src/azayaka.egg-info/top_level.txt
reading manifest file 'src/azayaka.egg-info/SOURCES.txt'
adding license file 'LICENSE'
writing manifest file 'src/azayaka.egg-info/SOURCES.txt'
installing to build/bdist.macosx-11.0-arm64/wheel
running install
running install_lib
creating build/bdist.macosx-11.0-arm64/wheel
creating build/bdist.macosx-11.0-arm64/wheel/azayaka
copying build/lib/azayaka/__init__.py -> build/bdist.macosx-11.0-arm64/wheel/./azayaka
running install_egg_info
Copying src/azayaka.egg-info to build/bdist.macosx-11.0-arm64/wheel/./azayaka-0.1.0-py3.11.egg-info
running install_scripts
creating build/bdist.macosx-11.0-arm64/wheel/azayaka-0.1.0.dist-info/WHEEL
creating '/Users/syu/src/git/azayaka/dist/.tmp-s2ns_65k/azayaka-0.1.0-py3-none-any.whl' and adding 'build/bdist.macosx-11.0-arm64/wheel' to it
adding 'azayaka/__init__.py'
adding 'azayaka-0.1.0.dist-info/licenses/LICENSE'
adding 'azayaka-0.1.0.dist-info/METADATA'
adding 'azayaka-0.1.0.dist-info/WHEEL'
adding 'azayaka-0.1.0.dist-info/top_level.txt'
adding 'azayaka-0.1.0.dist-info/RECORD'
removing build/bdist.macosx-11.0-arm64/wheel
Successfully built azayaka-0.1.0.tar.gz and azayaka-0.1.0-py3-none-any.whl
```


Artifacts will be created under `dist/`.

## Upload to TestPyPI (recommended)

Create or update `~/.pypirc`:

```ini
[distutils]
index-servers =
  testpypi
  pypi

[testpypi]
repository = https://test.pypi.org/legacy/
username = __token__
password = <TEST_PYPI_API_TOKEN>

[pypi]
repository = https://upload.pypi.org/legacy/
username = __token__
password = <PYPI_API_TOKEN>
```

Then upload:

```bash
python -m twine upload -r testpypi dist/*
```

Logs
```log
INFO     Using configuration from /Users/syu/.pypirc                                                                                               
Uploading distributions to https://test.pypi.org/legacy/
INFO     dist/azayaka-0.1.0-py3-none-any.whl (25.3 KB)                                                                                             
INFO     dist/azayaka-0.1.0.tar.gz (36.6 KB)                                                                                                       
INFO     username set by command options                                                                                                           
INFO     password set from config file                                                                                                             
INFO     username: __token__                                                                                                                       
INFO     password: <hidden>                                                                                                                        
Uploading azayaka-0.1.0-py3-none-any.whl
100% ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 69.5/69.5 kB • 00:00 • 313.2 MB/s
INFO     Response from https://test.pypi.org/legacy/:                                                                                              
         200 OK                                                                                                                                    
INFO     <html>                                                                                                                                    
          <head>                                                                                                                                   
           <title>200 OK</title>                                                                                                                   
          </head>                                                                                                                                  
          <body>                                                                                                                                   
           <h1>200 OK</h1>                                                                                                                         
           <br/><br/>                                                                                                                              
                                                                                                                                                   
                                                                                                                                                   
                                                                                                                                                   
          </body>                                                                                                                                  
         </html>                                                                                                                                   
Uploading azayaka-0.1.0.tar.gz
100% ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 81.0/81.0 kB • 00:00 • 245.9 MB/s
INFO     Response from https://test.pypi.org/legacy/:                                                                                              
         200 OK                                                                                                                                    
INFO     <html>                                                                                                                                    
          <head>                                                                                                                                   
           <title>200 OK</title>                                                                                                                   
          </head>                                                                                                                                  
          <body>                                                                                                                                   
           <h1>200 OK</h1>                                                                                                                         
           <br/><br/>                                                                                                                              
                                                                                                                                                   
                                                                                                                                                   
                                                                                                                                                   
          </body>                                                                                                                                  
         </html>                                                                                                                                   

View at:
https://test.pypi.org/project/azayaka/0.1.0/
```

## Upload to PyPI

```bash
python -m twine upload -r pypi dist/*
```

## Verify the release

```bash
python -m pip install -i https://test.pypi.org/simple/ azayaka
python -m pip show azayaka
```

If the TestPyPI install succeeds, repeat on PyPI without the custom index.

# Azayaka PyPI Webpage

## TestPyPI

https://test.pypi.org/project/azayaka/0.1.0/

## PyPI
https://pypi.org/project/azayaka/0.1.0/
