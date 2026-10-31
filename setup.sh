#!/usr/bin/env bash
# Sets up potato_home and starts it. Safe to run again at any time,
# for example after `git pull` to apply an update.
#
#   ./setup.sh           check, install what's missing, configure, build and start
#   ./setup.sh --check   only check and report; changes nothing
#
# Works on:
#   Arch Linux                                   (Docker from pacman)
#   Raspberry Pi OS 64-bit, Debian, Ubuntu       (Docker from Docker's apt repository)
#   macOS                                        (Docker Desktop, via Homebrew)
#
# Steps:
#   1. System: which one, not run as root
#   2. Packages: git, curl, Docker with Compose (installed with pacman/apt/brew, asks first)
#   3. Docker: running now and started on every boot
#   4. Docker access: directly, or through sudo
#   5. Settings: .env with API_TOKEN (generated), TELEGRAM_TOKEN (asked), TZ, MORNING_SUMMARY_TIME
#   6. Data folders: data/users, data/tickets, data/estate, data/bot
#   7. Start: build and start all services, then wait until each one answers
#   8. Summary: addresses, next steps, sleep/lid/firewall reminders
#
# Python and the Python libraries are NOT installed on this machine:
# every service brings its own inside its Docker image.
#
# Written for the old bash 3.2 of macOS too, so no bash 4 features.

# /etc/os-release is read on purpose, to learn which Linux this is:
# shellcheck disable=SC1091

set -euo pipefail

CHECK_ONLY=false
problems=0
OS=unknown  # arch, debian (incl. Raspberry Pi OS and Ubuntu), mac

# --- Output helpers ---------------------------------------------------------------

bold=$'\e[1m' green=$'\e[32m' yellow=$'\e[33m' red=$'\e[31m' reset=$'\e[0m'
step()    { echo; echo "${bold}==> $*${reset}"; }
ok()      { echo "  ${green}✓${reset} $*"; }
warn()    { echo "  ${yellow}!${reset} $*"; }
problem() { echo "  ${red}✗${reset} $*"; problems=$((problems + 1)); }
die()     { echo "  ${red}✗ $*${reset}"; exit 1; }

# ask "Question?" y|n  -> succeeds on yes; the second argument is the answer for plain Enter
ask() {
    local hint answer
    if [[ $2 == y ]]; then hint="Y/n"; else hint="y/N"; fi
    read -rp "  $1 [$hint] " answer || true
    case "${answer:-$2}" in
        [Yy]*) return 0 ;;
        *) return 1 ;;
    esac
}

# --- .env helpers -----------------------------------------------------------------

env_get() { grep -E "^$1=" .env 2>/dev/null | tail -n 1 | cut -d= -f2- || true; }

env_set() {  # replace the line, or add it if it's missing (works with macOS and Linux sed)
    if grep -qE "^$1=" .env; then
        sed "s|^$1=.*|$1=$2|" .env > .env.new && mv .env.new .env
    else
        echo "$1=$2" >> .env
    fi
    chmod 600 .env
}

# --- 1. System --------------------------------------------------------------------

check_system() {
    step "System"
    [[ $EUID -eq 0 ]] && die "Run this as your normal user, not root. It uses sudo when it needs to."
    if [[ $(uname -s) == Darwin ]]; then
        OS=mac
        ok "macOS $(sw_vers -productVersion)"
    elif [[ -f /etc/arch-release ]]; then
        OS=arch
        ok "Arch Linux"
    elif [[ -f /etc/debian_version ]]; then
        OS=debian
        ok "$(. /etc/os-release && echo "$PRETTY_NAME")"
    else
        warn "Unknown system: install git, curl and Docker with Compose yourself, the rest works the same."
    fi
}

# --- 2. Packages ------------------------------------------------------------------

install_packages() {
    step "Packages: git, curl, Docker with Compose"
    case $OS in
        arch) install_arch ;;
        debian) install_debian ;;
        mac) install_mac ;;
        *) if command -v docker >/dev/null; then ok "docker found"; else problem "docker is missing"; fi ;;
    esac
}

install_arch() {
    local packages=(git docker docker-compose docker-buildx curl) missing=() p
    for p in "${packages[@]}"; do
        pacman -Qi "$p" &>/dev/null || missing+=("$p")
    done
    if ((${#missing[@]} == 0)); then
        ok "all installed"
        return
    fi
    if $CHECK_ONLY; then
        problem "missing: ${missing[*]}"
        return
    fi
    echo "  Missing: ${missing[*]}"
    echo "  On Arch, installing packages means updating the whole system first (pacman -Syu)."
    ask "Update the system and install them now?" y \
        || die "Install them yourself, then run this again: sudo pacman -Syu ${missing[*]}"
    sudo pacman -Syu --needed --noconfirm "${missing[@]}"
    ok "installed"
}

install_debian() {
    local arch missing=() p need_docker=false
    arch=$(dpkg --print-architecture)
    if [[ $arch != arm64 && $arch != amd64 ]]; then
        die "This is a $arch (32-bit) system. Use a 64-bit OS: on a Raspberry Pi, Raspberry Pi OS (64-bit)."
    fi
    for p in git curl ca-certificates; do
        dpkg -s "$p" &>/dev/null || missing+=("$p")
    done
    if ! command -v docker >/dev/null || ! docker compose version &>/dev/null; then
        need_docker=true
    fi
    if ((${#missing[@]} == 0)) && ! $need_docker; then
        ok "all installed"
        return
    fi
    if $CHECK_ONLY; then
        problem "missing: ${missing[*]} $($need_docker && echo "Docker with Compose")"
        return
    fi
    echo "  Missing: ${missing[*]} $($need_docker && echo "Docker with Compose")"
    $need_docker && echo "  Docker comes from Docker's own apt repository (docs.docker.com/engine/install/debian)."
    ask "Install them now?" y || die "Install them yourself, then run this again."

    sudo apt-get update
    if ((${#missing[@]} > 0)); then
        sudo apt-get install -y "${missing[@]}"
    fi
    if $need_docker; then
        add_docker_apt_repository
        sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    fi
    ok "installed"
}

add_docker_apt_repository() {
    # As in Docker's instructions: their signing key, then their repository for this release
    local distro codename
    distro=$(. /etc/os-release && echo "$ID")
    [[ $distro == ubuntu ]] || distro=debian  # Raspberry Pi OS and other Debian relatives use Debian's
    codename=$(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
    sudo install -m 0755 -d /etc/apt/keyrings
    sudo curl -fsSL "https://download.docker.com/linux/$distro/gpg" -o /etc/apt/keyrings/docker.asc
    sudo chmod a+r /etc/apt/keyrings/docker.asc
    sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/$distro
Suites: $codename
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
    sudo apt-get update
}

install_mac() {
    if command -v git >/dev/null; then
        ok "git"
    else
        $CHECK_ONLY && { problem "git is missing (install it: xcode-select --install)"; return; }
        die "git is missing: run xcode-select --install, then run this again"
    fi
    if command -v docker >/dev/null; then
        ok "Docker Desktop"
        return
    fi
    $CHECK_ONLY && { problem "Docker Desktop isn't installed"; return; }
    echo "  On a Mac, Docker comes as the Docker Desktop app (free for personal use, needs macOS 14+)."
    if command -v brew >/dev/null && ask "Install it with Homebrew (brew install --cask docker-desktop)?" y; then
        brew install --cask docker-desktop
        ok "installed"
    else
        die "Install Docker Desktop from https://www.docker.com/products/docker-desktop/, then run this again."
    fi
}

# --- 3. Docker service ------------------------------------------------------------

start_docker() {
    step "Docker service"
    if [[ $OS == mac ]]; then
        start_docker_desktop
    elif [[ ! -d /run/systemd/system ]]; then
        warn "systemd isn't running here: make sure the Docker daemon runs"
    elif systemctl is-enabled --quiet docker 2>/dev/null && systemctl is-active --quiet docker; then
        ok "running, and starts on boot"
    elif $CHECK_ONLY; then
        problem "Docker isn't running or isn't started on boot (fix: sudo systemctl enable --now docker)"
    else
        sudo systemctl enable --now docker
        ok "started, and enabled on boot"
    fi
}

start_docker_desktop() {
    if docker info &>/dev/null; then
        ok "Docker Desktop is running"
        return
    fi
    $CHECK_ONLY && { problem "Docker Desktop isn't running (start it from Applications)"; return; }
    echo "  Starting Docker Desktop (the first start may ask you to accept its terms)..."
    open -a Docker
    for _ in $(seq 1 60); do
        docker info &>/dev/null && { ok "Docker Desktop is running"; return; }
        sleep 2
    done
    die "Docker Desktop didn't start within 2 minutes: open it from Applications, then run this again"
}

# --- 4. Docker access -------------------------------------------------------------

DOCKER=(docker)
COMPOSE=(docker compose)

check_docker_access() {
    step "Docker access"
    if docker info &>/dev/null; then
        DOCKER=(docker)
        ok "you can use Docker directly"
    elif [[ $OS != mac ]] && sudo docker info &>/dev/null; then
        DOCKER=(sudo docker)
        warn "you can use Docker only with sudo (this script will use sudo)"
        if ! $CHECK_ONLY && ! id -nG "$USER" | grep -qw docker; then
            echo "  Being in the 'docker' group lets you run docker without sudo."
            echo "  Note: members of that group effectively have root access to this machine."
            if ask "Add $USER to the docker group?" n; then
                sudo usermod -aG docker "$USER"
                ok "added: takes effect after you log out and back in"
            fi
        fi
    else
        $CHECK_ONLY && { problem "Docker doesn't answer"; return; }
        die "Docker doesn't answer. On Linux look at: sudo systemctl status docker"
    fi

    # The compose plugin (`docker compose`) or the standalone `docker-compose`
    if "${DOCKER[@]}" compose version &>/dev/null; then
        COMPOSE=("${DOCKER[@]}" compose)
    elif command -v docker-compose >/dev/null; then
        COMPOSE=(docker-compose)
        [[ ${DOCKER[0]} == sudo ]] && COMPOSE=(sudo docker-compose)
    else
        $CHECK_ONLY && { problem "Docker Compose is missing"; return; }
        die "Docker Compose is missing"
    fi
    ok "compose: $("${COMPOSE[@]}" version --short 2>/dev/null || echo found)"
}

# --- 5. Settings (.env) -----------------------------------------------------------

setup_env() {
    step "Settings (.env)"
    if [[ ! -f .env ]]; then
        $CHECK_ONLY && { problem ".env doesn't exist yet"; return; }
        cp .env.example .env
        ok "created .env from .env.example"
    fi
    $CHECK_ONLY || chmod 600 .env  # it holds secrets: readable only by you

    local token
    token=$(env_get API_TOKEN)
    if [[ -z $token || $token == change-me ]]; then
        if $CHECK_ONLY; then
            problem "API_TOKEN isn't set"
        else
            # 40 random hex characters
            env_set API_TOKEN "$(od -An -N20 -tx1 /dev/urandom | tr -d ' \n')"
            ok "generated a random API_TOKEN"
        fi
    else
        ok "API_TOKEN is set"
    fi

    token=$(env_get TELEGRAM_TOKEN)
    if [[ -n $token ]]; then
        ok "TELEGRAM_TOKEN is set"
    elif $CHECK_ONLY; then
        problem "TELEGRAM_TOKEN is empty: the bot can't start"
    else
        echo "  The Telegram bot needs a token from @BotFather (see SETUP.md)."
        read -rsp "  Paste it here (hidden), or press Enter to skip the bot for now: " token || true
        echo
        if [[ -z $token ]]; then
            warn "skipped: everything starts without the bot. Run ./setup.sh again to add it."
        elif [[ $token =~ ^[0-9]+:[A-Za-z0-9_-]+$ ]]; then
            env_set TELEGRAM_TOKEN "$token"
            ok "TELEGRAM_TOKEN saved"
        else
            die "That doesn't look like a bot token (it looks like 123456789:ABC-def_...)."
        fi
    fi

    local tz morning
    tz=$(env_get TZ)
    if [[ -z $tz ]]; then
        problem "TZ is empty: set it in .env, e.g. TZ=Europe/Riga"
    elif [[ -d /usr/share/zoneinfo && ! -e /usr/share/zoneinfo/$tz ]]; then
        problem "TZ=$tz isn't a known timezone"
    else
        ok "TZ=$tz"
    fi

    morning=$(env_get MORNING_SUMMARY_TIME)
    if [[ -z $morning ]]; then
        ok "MORNING_SUMMARY_TIME not set: 08:30"
    elif [[ $morning =~ ^([01][0-9]|2[0-3]):[0-5][0-9]$ ]]; then
        ok "MORNING_SUMMARY_TIME=$morning"
    else
        problem "MORNING_SUMMARY_TIME=$morning should look like 08:30"
    fi
}

# --- 6. Data folders --------------------------------------------------------------

setup_data() {
    step "Data folders"
    local dir
    for dir in data/users data/tickets data/estate data/bot; do
        if [[ -d $dir ]]; then
            continue
        elif $CHECK_ONLY; then
            warn "$dir doesn't exist yet"
        else
            mkdir -p "$dir"  # created by you, not by Docker as root
        fi
    done
    if [[ -f data/users/users.db ]]; then
        ok "existing data found: it will be used"
    else
        ok "fresh start: users come from services/users/users.yaml on the first start"
    fi
    if [[ -f data/tickets.db ]]; then
        warn "data/tickets.db is the old layout (before users moved out): see SETUP.md, 'Bring your data'"
    fi
}

# --- 7. Build and start -----------------------------------------------------------

wait_for() {  # wait_for NAME COMMAND...: retries for up to 90 seconds
    local name=$1
    shift
    for _ in $(seq 1 45); do
        if "$@" &>/dev/null; then
            ok "$name answers"
            return 0
        fi
        sleep 2
    done
    problem "$name doesn't answer: see ${COMPOSE[*]} logs $name"
}

bot_health() {
    "${COMPOSE[@]}" exec -T bot python -c \
        "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"
}

start_services() {
    step "Services"
    local services=(users tickets estate screen bot)
    [[ -z $(env_get TELEGRAM_TOKEN) ]] && services=(users tickets estate screen)

    if $CHECK_ONLY; then
        local status service
        status=$("${COMPOSE[@]}" ps --format '{{.Service}}: {{.Status}}' 2>/dev/null || true)
        if [[ -z $status ]]; then
            problem "nothing is running (start everything: ./setup.sh)"
            return
        fi
        for service in "${services[@]}"; do
            if ! grep -q "^$service: Up" <<< "$status"; then
                problem "$service isn't running"
            elif grep -q "^$service: .*unhealthy" <<< "$status"; then
                problem "$service runs but is unhealthy: see ${COMPOSE[*]} logs $service"
            else
                ok "$service: $(grep "^$service: " <<< "$status" | cut -d' ' -f2-)"
            fi
        done
        return
    fi
    echo "  Building and starting: ${services[*]} (the first build takes a few minutes)"
    "${COMPOSE[@]}" up -d --build "${services[@]}"

    wait_for users   curl -sf http://localhost:8002/health
    wait_for tickets curl -sf http://localhost:8001/health
    wait_for estate  curl -sf http://localhost:8003/health
    wait_for screen  curl -sf http://localhost:8080/health
    if [[ " ${services[*]} " == *" bot "* ]]; then
        wait_for bot bot_health
    fi
}

# --- 8. Summary -------------------------------------------------------------------

home_address() {  # this machine's address on the home network (empty if offline)
    if [[ $OS == mac ]]; then
        ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true
    else
        ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (i = 1; i < NF; i++) if ($i == "src") print $(i + 1)}' || true
    fi
}

reminders() {  # things outside this project that stop the services or hide the screen
    if [[ $OS == mac ]]; then
        warn "Docker Desktop must start when you sign in: Docker Desktop → Settings → General"
        if /usr/libexec/ApplicationFirewall/socketfilterfw --getblockall 2>/dev/null | grep -q "blocking all"; then
            warn "The Mac's firewall blocks all incoming connections: the TV can't open the screen (see SETUP.md)"
        fi
        if pmset -g 2>/dev/null | grep -qE '^ +sleep +[1-9]'; then
            warn "This Mac goes to sleep when idle, which stops everything: see SETUP.md, 'Keep it running'"
        fi
    elif ls /sys/class/power_supply/BAT* &>/dev/null \
        && ! grep -qsE '^\s*HandleLidSwitch\s*=\s*ignore' /etc/systemd/logind.conf /etc/systemd/logind.conf.d/*.conf; then
        warn "Closing the laptop lid will suspend it and stop everything: see SETUP.md, 'Keep it running'"
    fi
}

summary() {
    step "Summary"
    local ip
    ip=$(home_address)
    echo "  Info screen for the TV:  http://${ip:-<this-machine>}:8080"
    echo "  Health of all services: shown on the screen; or ./setup.sh --check"
    reminders

    if ((problems > 0)); then
        echo; echo "  ${red}${problems} problem(s) found: see the ✗ lines above.${reset}"
        exit 1
    fi
    echo; echo "  ${green}All good.${reset}"
    $CHECK_ONLY || echo "  Next steps (Telegram, your data from the old machine): see SETUP.md"
}

main() {
    cd "$(dirname "$0")"
    [[ "${1:-}" == "--check" ]] && CHECK_ONLY=true
    check_system
    install_packages
    start_docker
    check_docker_access
    setup_env
    setup_data
    start_services
    summary
}

# Run only when executed, not when loaded by `source setup.sh` (as the tests do)
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
