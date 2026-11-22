# Invoked by SSH with an open stdin. EOF requests cleanup even if the client dies.
set -euo pipefail
repo=$1 sha=$2 scenario=$3 run=$4
[[ $sha =~ ^[a-f0-9]{40}$ && $run =~ ^[a-f0-9]{32}$ ]]
case "$scenario" in
  asr|first-pcm|between|playing|release|late|blackhole|disconnect) ;;
  *) exit 2 ;;
esac
git -C "$repo" cat-file -e "$sha^{commit}" || { printf 'ERROR checkout\n'; exit 1; }
# Serialize this tool's remote sessions. A preexisting manual service is never stopped.
lock_dir="$HOME/.cache/little-buddy-oppo-regression"
mkdir -p -m 700 "$lock_dir"
exec 9<>"$lock_dir/fixture.lock"
flock -n 9 || { printf 'ERROR busy\n'; exit 1; }
listeners=$(ss -H -ltn 'sport = :9444')
[[ -z $listeners ]] || { printf 'ERROR busy\n'; exit 1; }
unit="little-buddy-regression-$run-$scenario.service"
staging=$(sudo -n mktemp -d /run/little-buddy-regression.XXXXXXXX)
started=0
cleanup() {
  local result=$? cleaned=1
  trap - EXIT
  if (( started )); then
    sudo -n systemctl stop "$unit" || cleaned=0
  fi
  sudo -n rm -rf -- "$staging" || cleaned=0
  if (( cleaned )); then
    printf 'STOPPED %s\n' "$unit"
  else
    printf 'CLEANUP_FAILED %s\n' "$unit"
    result=1
  fi
  exit "$result"
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM
git -C "$repo" archive "$sha" backend | sudo -n tar -x -C "$staging"
sudo -n chmod 755 "$staging"
sudo -n systemd-run --unit="$unit" --quiet --collect \
  -p DynamicUser=yes -p NoNewPrivileges=yes -p ProtectSystem=strict \
  -p RuntimeMaxSec=180s -p TimeoutStopSec=5s -p MemoryMax=256M -p LimitCORE=0 \
  -p LoadCredential=voice-cert:/etc/little-buddy/voice/loopback-cert.pem \
  -p LoadCredential=voice-key:/etc/little-buddy/voice/loopback-key.pem \
  --working-directory="$staging" /usr/bin/python3 -B -m backend.animal.private_fixture \
  "$scenario" --port 9444 --cert '${CREDENTIALS_DIRECTORY}/voice-cert' \
  --key '${CREDENTIALS_DIRECTORY}/voice-key'
started=1
for ((i=0; i<40; i++)); do
  sudo -n systemctl is-active --quiet "$unit" || exit 1
  if sudo -n journalctl --unit "$unit" --no-pager --output=cat |
    awk -v marker="animal_fixture_ready scenario=$scenario port=9444" '$0 == marker {ready=1} END {exit !ready}'; then
    printf 'READY %s\n' "$unit"
    break
  fi
  sleep 0.25
done
(( i < 40 )) || exit 1
while sudo -n systemctl is-active --quiet "$unit"; do
  if IFS= read -r -t 1 command; then
    [[ $command == STOP ]] && exit 0
    exit 1
  else
    status=$?
    (( status > 128 )) || exit 0
  fi
done
exit 1
