#!/bin/bash 

filename="gw_bulk.py"
rmpy=${filename%.py}

vi $filename

printf "Clearing old directories / files \n"
rm -v -R build dist $rmpy.spec __pycache__

printf "run pyinstaller for gw_rename.py\n"
python3 -m PyInstaller $filename --onefile

