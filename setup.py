import os
from setuptools import setup, find_packages

# Utility function to read the README file.
def read(fname):
    return open(os.path.join(os.path.dirname(__file__), fname), encoding="UTF-8").read()

setup(
    name = "srdl2sv",
    version = "0.0.1",
    author = "Dennis Potter",
    author_email = "dennis@dennispotter.eu",
    maintainer = "Dennis Potter",
    maintainer_email = "dennis@dennispotter.eu",
    description = ("A SystemRDL 2.0 to (synthesizable) SystemVerilog compiler."),
    license = "GPLv3",
    keywords = "systemverilog verilog systemrdl rdl hdl rtl",
    url = "https://git.dennispotter.eu/Dennis/srdl2sv",
    packages=['srdl2sv',
              'srdl2sv.components',
              'srdl2sv.components.templates',
              'srdl2sv.components.widgets',
              'srdl2sv.cli',
              'srdl2sv.log'],
    include_package_data=True,
    entry_points = {
        'console_scripts': ['srdl2sv=srdl2sv.srdl2sv:main', ]
    },
    long_description=read('README.md'),
    # Note that install_requires differs from requirements.txt
    # since it does not include any of the files that are used
    # to perform tests (i.e., cocotb)
    install_requires=[
   'PyYAML==6',
   'systemrdl-compiler>=1.18.0, <2'
    ],
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
        "Programming Language :: Python :: 3 :: Only",
        "Topic :: Software Development :: Compilers",
        "Topic :: Software Development :: Code Generators",
    ],
)
