#!/bin/bash
set -e

cd client
npm install
npm run build
cd ..

rm -rf server/dist
mv client/dist server/public
