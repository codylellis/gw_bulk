#!/bin/bash 

read -p "Main script: " filename

read -p "Enter git comment: " com

git add $filename dist/ pycompile.sh gitpush.sh
git commit -m "$com"

git push -u origin main

