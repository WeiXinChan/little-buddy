#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
mode=${1:-}
venv=$(realpath "${2:?usage: private.sh fake|dashscope|ab|ab-seed /path/to/venv [synthetic.pcm]}")
[[ -x "$venv/bin/python" ]]
case "$mode" in
  fake|dashscope|ab-seed) [[ $# == 2 ]] ;;
  ab)
    [[ $# == 3 && -f "$3" && -r "$3" ]]
    input_size=$(stat -Lc %s -- "$3")
    ((input_size > 0 && input_size <= 320000 && input_size % 2 == 0))
    ;;
  *) exit 2 ;;
esac
lock=/var/lock/little-buddy/heavy.lock
[[ ! -L "$lock" && $(stat -c '%u:%g:%a' "$lock") == 0:0:644 ]]
exec 9<"$lock"
flock -n -E 75 9
[[ -z "$(ss -Hln 'sport = :8444')" ]] || { echo "8444 busy" >&2; exit 75; }

staging=$(sudo -n mktemp -d /run/little-buddy-pipecat.XXXXXXXX)
unit="${staging##*/}.service"
cleanup() {
  sudo -n systemctl stop "$unit" 2>/dev/null || true
  sudo -n rm -rf -- "$staging"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' HUP TERM
sudo -n chmod 755 "$staging"
sudo -n mkdir "$staging/venv"
sudo -n cp -r backend experiments "$staging/"
directory=/etc/little-buddy/voice
credentials=(
  -p "LoadCredential=voice-device-token:$directory/device-token"
  -p "LoadCredential=voice-cert:$directory/loopback-cert.pem"
  -p "LoadCredential=voice-key:$directory/loopback-key.pem"
)
if [[ "$mode" != fake ]]; then
  credentials+=(
    -p "EnvironmentFile=$directory/dashscope.env"
    -p "LoadCredential=dashscope-api-key:$directory/dashscope-api-key"
  )
fi
if [[ "$mode" == ab || "$mode" == ab-seed ]]; then
  sudo -n mkdir "$staging/baseline"
  git archive 0707ffc6844c0c4c4ad9343c37a01fb694ae076a backend | sudo -n tar -x -C "$staging/baseline"
  sudo -n cp -r experiments "$staging/baseline/"
  if [[ "$mode" == ab ]]; then
    sudo -n install -m 0644 "$3" "$staging/input.pcm"
  fi
  credentials+=(-p "LoadCredential=voice-ca:$directory/loopback-ca.pem")
  command=(-m experiments.pipecat.ab)
  if [[ "$mode" == ab-seed ]]; then command+=(--seed); fi
else
  command=(-m experiments.pipecat.pipeline --provider "$mode" --timings
           --cert '${CREDENTIALS_DIRECTORY}/voice-cert' --key '${CREDENTIALS_DIRECTORY}/voice-key')
fi
exec 8<&0
sudo -n systemd-run --unit="$unit" --quiet --wait --pipe --collect \
  -p DynamicUser=yes -p NoNewPrivileges=yes -p ProtectSystem=strict \
  -p "BindReadOnlyPaths=$venv:$staging/venv" \
  -p RuntimeMaxSec=15min -p TimeoutStopSec=5 -p CPUQuota=100% \
  -p MemoryMax=512M -p MemorySwapMax=0 -p TasksMax=32 -p LimitCORE=0 \
  --setenv=OMP_NUM_THREADS=1 --setenv=OPENBLAS_NUM_THREADS=1 \
  --setenv=HF_HUB_OFFLINE=1 --setenv=PYTHONUNBUFFERED=1 \
  "${credentials[@]}" --working-directory="$staging" \
  /usr/bin/env "$staging/venv/bin/python" -B "${command[@]}" <&8 &
launcher=$!
wait "$launcher"
