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
  install_requires=["IPython", "metakernel", "xmltodict", "xml", "numpy", "pandas",
                    "matplotlib", "pexpect"]
  )
