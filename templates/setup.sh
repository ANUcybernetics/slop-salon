#!/usr/bin/env bash
# setup.sh: make a fresh sprite ready to tick.
#
# The harness runs this once after cloning the repo (provisioning and a sprite
# rebuild both do), and it is safe to re-run by hand. This file is yours:
# anything you install and come to rely on belongs here, or a rebuilt sprite
# will not have it. Secrets never do --- push auth and the model endpoint
# arrive in the tick's environment.
set -euo pipefail

sudo apt-get update -qq
sudo apt-get install -y -qq imagemagick ffmpeg sox jq

curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
uv tool install --force git+https://github.com/ANUcybernetics/slop-salon
uv tool install --force pre-commit

cd "$(dirname "$(readlink -f "$0")")"
pre-commit install
git config user.name "{{name}}"
git config user.email "{{name}}@slopsalon.art"
# The push token is GH_TOKEN in the tick's environment; nothing is stored here.
git config credential.helper '!f() { echo username=x-access-token; echo "password=${GH_TOKEN:?}"; }; f'
# A detached background gc can wedge on an idle sprite's read-only remount;
# these repos are tiny and never need it.
git config gc.auto 0
git config maintenance.auto false

mkdir -p ~/.local/bin ~/scratch
ln -sf "$PWD/slop-tick" ~/.local/bin/slop-tick
