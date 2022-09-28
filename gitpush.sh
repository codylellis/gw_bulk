#!/bin/bash 

read -p "Main script: " filename

read -p "Enter git comment: " com

git add $filename gitpush.sh README.md
git commit -m "$com"

git push -u origin main

