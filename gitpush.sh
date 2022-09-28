#!/bin/bash 

read -p "Enter git comment: " com

git add gw_bulk.py gitpush.sh README.md
git commit -m "$com"

git push -u origin main

