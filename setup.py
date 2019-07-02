# Definition of the SPM kernel class SPMKernel
# Copyright (C) 2019 John L. Ries

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import io
import pathlib
import os
from setuptools import setup

# The directory containing this file
HERE = pathlib.Path(__file__).parent

# The text of the README file
README = (HERE / "README.md").read_text()

#Extract version number
with io.open("spm_kernel/version.py", encoding='utf-8') as fid:
  for line in fid:
    if line.startswith('__version__'):
      __version__ = line.strip().split()[-1][1:-1]
      break

# This call to setup() does all the work
setup(
  name = "spm_kernel",
  version = __version__,
  description = "Jupyter kernel for Salford Predictive Miner (SPM)",
  long_description=README,
  long_description_content_type="text/markdown",
  url="https://github.com/jlries61/spm_kernel",
  author="John L. Ries",
  author_email="john@theyarnbard.com",
  license="GPLv3",
  packages=["spm_kernel"],
  requires_python=">=3.6",
  install_requires=["IPython", "metakernel", "xmltodict", "numpy", "pandas",
                    "matplotlib", "pexpect", "ordered-set"]
  )
