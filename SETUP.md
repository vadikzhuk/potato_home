# Setup: from GitHub to a machine that runs everything

This guide puts potato_home on an always-on machine at home:

1. Pick a machine
2. Upload the project to GitHub
3. Prepare the machine
4. Clone and run `setup.sh`
5. Bring your data from the old machine (optional)
6. Connect Telegram
7. Keep it running
8. The screen on the TV

Updates, backups and troubleshooting are at the end.

Everything runs in Docker. The machine needs only git and Docker. Python and all
libraries come inside each service's Docker image. Together the services need about
200 MB of memory.

---

## 1. Pick a machine

| Machine | Good for | Mind |
|---|---|---|
| **Old laptop with Arch Linux** | free, has a screen and keyboard for fixing things | closing the lid suspends it; uses more power |
| **Raspberry Pi 4 or 5** (2 GB+) with Raspberry Pi OS 64-bit | small, silent, 3–5 W; can drive the TV over HDMI itself | SD cards wear out: a USB SSD is better; Pi 3 works but builds slowly |
| **MacBook** with macOS 14+ | easy if you have one spare | Docker Desktop runs only while you're signed in; sleeps by default |

`setup.sh` works on all three. It also works on Debian or Ubuntu, and on other Linux if
Docker is already installed. 32-bit systems (old Pis, the 32-bit Raspberry Pi OS) are not supported.

## 2. Upload to GitHub (on the machine you develop on)

Secrets and data are never uploaded. `.gitignore` keeps out `.env` (tokens) and
`data/` (databases), and also virtual environments and caches. To check what would
be uploaded:

```bash
git status --short --untracked-files=all
```

There must be no `.env`, no `.db` files and nothing from `data/` except `data/.gitkeep`.

Create an **empty** repository on github.com: choose no README, no .gitignore and
no license. The project already has all three (the licence is MIT, in `LICENSE`). If
GitHub creates any of them, your first push is refused. Then:

```bash
git add .
git commit -m "potato_home: users, tickets, info screen, Telegram bot"
git remote add origin git@github.com:<your-name>/potato_home.git
git push -u origin main
```

## 3. Prepare the machine

### Arch Linux laptop

Install git (setup.sh installs the rest):

```bash
sudo pacman -Syu --needed git
```

### Raspberry Pi

1. Get the OS onto the card or SSD:
   1. With **Raspberry Pi Imager** on another computer, choose **Raspberry Pi OS (64-bit)**.
      - *Lite* has no desktop: enough if the TV has its own browser.
      - Choose the version with a desktop if the Pi should show the screen on the TV
        itself (section 8).
   2. In Imager's settings, set a hostname (e.g. `potato`), your user and password, Wi-Fi,
      and **enable SSH**.
2. Boot the Pi and log in. From another computer: `ssh <you>@potato.local`.
3. Install git:
   ```bash
   sudo apt update && sudo apt install -y git
   ```

A good A1/A2 SD card works. A USB SSD (Pi 4/5) is faster and lasts much longer.

### MacBook

1. Install git: `xcode-select --install` (installs Apple's command line tools).
2. Docker Desktop is installed by setup.sh with [Homebrew](https://brew.sh) if you
   have it. Otherwise download it from
   [docker.com](https://www.docker.com/products/docker-desktop/) and open it once to
   accept its terms. It's free for personal use.

## 4. Clone and run setup.sh

```bash
git clone https://github.com/<your-name>/potato_home.git ~/potato_home
cd ~/potato_home
./setup.sh
```

The repository is public, so cloning with `https://` needs no login. For a private
repository, add an SSH key (`ssh-keygen -t ed25519`) to GitHub and clone with
`git@github.com:...`.

`setup.sh` is safe to run again any time. It only does what's still missing. It asks before:

- installing software (on Arch, together with a full system update)
- adding you to the docker group (Linux only)
- saving the Telegram token (see section 6; you can skip it and add it later)

To only see what's missing or broken, without changing anything:

```bash
./setup.sh --check
```

### What setup.sh does, step by step

The same steps by hand, so you know what happens (or can do it yourself):

1. **Install git, curl, and Docker with Compose:**
   - **Arch:** `sudo pacman -Syu --needed git docker docker-compose docker-buildx curl`
   - **Raspberry Pi OS, Debian, Ubuntu:** Docker comes from Docker's own repository,
     as in [Docker's instructions](https://docs.docker.com/engine/install/debian/):
     ```bash
     sudo apt-get update && sudo apt-get install -y git curl ca-certificates
     sudo install -m 0755 -d /etc/apt/keyrings
     sudo curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
     sudo chmod a+r /etc/apt/keyrings/docker.asc
     sudo tee /etc/apt/sources.list.d/docker.sources <<EOF
     Types: deb
     URIs: https://download.docker.com/linux/debian
     Suites: $(. /etc/os-release && echo "$VERSION_CODENAME")
     Components: stable
     Architectures: $(dpkg --print-architecture)
     Signed-By: /etc/apt/keyrings/docker.asc
     EOF
     sudo apt-get update
     sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
     ```
     (On Ubuntu, use `linux/ubuntu` instead of `linux/debian`.)
   - **macOS:** `brew install --cask docker-desktop`, or download Docker Desktop.
2. **Start Docker now and on every boot:**
   - **Linux:** `sudo systemctl enable --now docker`
   - **macOS:** open Docker Desktop. In its Settings → General, turn on
     *Start Docker Desktop when you sign in*.
3. **Linux only: Docker without sudo (optional).** Members of the `docker` group
   effectively have root access, which is fine on a home server you alone use. Log out
   and in afterwards. Without it, put `sudo` before every `docker` command.
   ```bash
   sudo usermod -aG docker $USER
   ```
4. **Settings.** `.env` holds the secrets and is readable only by you:
   ```bash
   cp .env.example .env && chmod 600 .env
   ```
   Then edit it:
   - `API_TOKEN`: a long random string the services use to talk to each other.
     setup.sh generates one; by hand: `od -An -N20 -tx1 /dev/urandom | tr -d ' \n'`
   - `TELEGRAM_TOKEN`: the bot token, see section 6
   - `TZ`: your timezone, e.g. `Europe/Riga`
   - `MORNING_SUMMARY_TIME`: when the bot sends the morning summary, e.g. `08:30`
5. **Data folders.** Create them yourself, so Docker doesn't create them owned by root:
   ```bash
   mkdir -p data/users data/tickets data/bot
   ```
6. **Build and start.** The first build takes a few minutes, longer on a Pi:
   ```bash
   docker compose up -d --build
   ```
7. **Check that each service answers:**
   ```bash
   docker compose ps    # all should become "(healthy)" within a minute
   curl localhost:8002/health; curl localhost:8001/health; curl localhost:8080/health
   ```

On a fresh start the users service creates the users listed in
`services/users/users.yaml`: one user called `admin` with full rights. If you bring
your data from the old machine (section 5), that file isn't used.

## 5. Bring your data from the old machine (optional)

Skip this to start fresh. Otherwise, your users, tickets with their history, and the
bot's notification state move over like this:

1. **On the old machine,** stop everything for good. Only one bot may run per Telegram
   token: two at once fight over the messages ("409 Conflict" in the bot log).
   ```bash
   cd <the potato_home folder>
   docker compose down
   ```
2. **On the new machine,** stop the services if setup.sh already started them
   (`docker compose down`). Make sure you can reach it with `ssh` from the old one:
   - **Arch:** `sudo systemctl enable --now sshd`
   - **Raspberry Pi:** enabled in Imager
   - **macOS:** System Settings → General → Sharing → Remote Login
3. **On the old machine,** copy the data. The trailing slashes matter:
   ```bash
   rsync -av --exclude backups data/ <you>@<new-machine>:~/potato_home/data/
   ```
   Or use a USB stick: copy the folders `data/users`, `data/tickets` and `data/bot`.
4. **On the new machine:**
   ```bash
   ./setup.sh
   ```

Only copy data while the services are stopped on both sides. A database copied while
in use may be incomplete.

## 6. Connect Telegram

1. In Telegram, talk to [@BotFather](https://t.me/BotFather): send `/newbot` and pick a
   name. It gives you a token. If you already have a bot, reuse its token: it's in the
   old machine's `.env`, which isn't uploaded.
2. Run `./setup.sh` and paste the token when asked. Or put it into `.env` as
   `TELEGRAM_TOKEN=...` and run `docker compose up -d bot`.
3. Turn off groups for the bot: in @BotFather, `/mybots` → your bot → Bot Settings →
   Allow Groups → Turn off.
4. **If you started fresh** (no data from an old machine):
   1. Send `/start` to your bot. It answers with your Telegram id.
   2. Connect the `admin` user to it:
      ```bash
      docker compose exec users users edit admin --telegram-id <your id>
      ```
   3. To use your own name:
      ```bash
      docker compose exec users users edit admin --name YourName
      ```
   4. Send `/help` to the bot.
5. Add family members:
   1. They send `/start` to get their id.
   2. You send `/user_add Anna <id>`, then `/user_grant Anna tickets write`.

## 7. Keep it running

**Everywhere:**

- **After a reboot or power cut:** Docker starts with the system, and every service is
  set to `restart: unless-stopped`, so they all come back by themselves. On a Mac this
  needs the sign-in described below.
- **Fixed address:** in your router, give the machine a fixed IP (often called
  "DHCP reservation"). Then the address on the TV never changes.
- **Never forward ports** to this machine on the router. Nothing here needs to be
  reachable from the internet, and the bot works without it.
- **Logs:** Docker keeps at most 3 × 10 MB of logs per service, so the disk doesn't fill up.

### Arch Linux laptop

**Lid closed:** by default, closing the lid suspends the laptop and everything stops.
Tell systemd to ignore the lid:

```bash
sudo mkdir -p /etc/systemd/logind.conf.d
printf '[Login]\nHandleLidSwitch=ignore\nHandleLidSwitchExternalPower=ignore\nHandleLidSwitchDocked=ignore\n' \
  | sudo tee /etc/systemd/logind.conf.d/lid.conf
sudo systemctl restart systemd-logind   # this ends your desktop session, if you have one
```

**Correct time,** so due dates, "overdue" and the morning summary are right:

```bash
sudo timedatectl set-ntp true
```

**Power cuts:** some laptops have a BIOS option "Power on when AC is connected" to switch
on again after a power cut.

### Raspberry Pi

- **Power supply:** use the official one. Weak supplies cause random crashes and
  corrupted SD cards.
- **Clock:** the Pi has no clock battery, but it sets its time from the internet at boot.
  That's on by default.
- **Power cuts:** a Pi starts again by itself when power comes back.

### MacBook

Docker Desktop is an app: it runs only while you're signed in, and only while the Mac
is awake.

1. **Start with the Mac:** Docker Desktop → Settings → General → *Start Docker Desktop
   when you sign in to your computer*.
2. **Sign in after a restart:** System Settings → Users & Groups → *Automatically log in
   as* your user. This isn't available while FileVault is on. Then, after a power cut or
   an update, someone has to sign in once.
3. **No sleep on the charger:** System Settings → Battery → Options → *Prevent automatic
   sleeping on power adapter when the display is off*. Or:
   ```bash
   sudo pmset -c sleep 0
   ```
4. **Lid:** a MacBook sleeps when you close the lid. Keep it open; you can dim the
   screen to nothing.
5. **macOS updates** restart the Mac. With automatic login, everything comes back by itself.

## 8. The screen on the TV

Open `http://<machine-ip>:8080` in the TV's browser, in full screen. setup.sh prints the
address at the end.

**A Raspberry Pi can show it itself.** Connect it to the TV with HDMI and use Raspberry
Pi OS *with desktop*:

1. Open the screen full-screen on every start, for example by adding this line to
   `~/.config/labwc/autostart`:
   ```bash
   chromium --kiosk --noerrdialogs --disable-infobars http://localhost:8080 &
   ```
   On older Raspberry Pi OS the browser is called `chromium-browser`.
2. Turn off screen blanking: Raspberry Pi Configuration → Display.

**Firewalls:** the TV must be able to reach port 8080 on the machine. The users and
tickets APIs (8002, 8001) answer only on the machine itself, on purpose.

- **Linux:** Arch and Raspberry Pi OS have no firewall by default. If you turned on `ufw`
  or `firewalld`, allow port 8080 from your home network.
- **macOS:** if System Settings → Network → Firewall → Options has *Block all incoming
  connections* on, the TV can't connect. Turn that off, and allow incoming connections
  for Docker when macOS asks. setup.sh warns when this is the case.

---

## Updating

When you change something and push it, update the machine with:

```bash
cd ~/potato_home
git pull
./setup.sh
```

setup.sh rebuilds only what changed. Your data and `.env` stay as they are.

When an update brings a **new service**, setup.sh creates its data folder and starts it,
but nobody has access to it yet. Give it to yourself (and others) by name, e.g. for estate:

```bash
users grant YourName estate admin
users grant Anna estate read
```

## Backups

All data is in `data/`, a few small files. To make a copy:

```bash
cd ~/potato_home
docker compose stop
tar czf ~/potato_home-backup-$(date +%F).tar.gz data .env
docker compose start
```

Keep that file somewhere else too: another disk, or another computer. It includes your
tokens. To restore: stop the services, unpack it into `~/potato_home`, then run `./setup.sh`.

## Troubleshooting

| What you see | What to do |
|---|---|
| Something is red on the screen | `./setup.sh --check`, then `docker compose logs --tail 50 <service>` |
| Bot log says `409 Conflict` | another copy of the bot runs with the same token, e.g. on the old machine: stop it there |
| Bot log says `TELEGRAM_TOKEN is empty` | add the token to `.env`, then `docker compose up -d bot` |
| `permission denied` with docker (Linux) | use `sudo docker ...`, or log out and in after joining the docker group |
| setup.sh says the system is 32-bit (`armhf`) | install the 64-bit Raspberry Pi OS |
| TV can't open the screen | is the IP right? Does `curl localhost:8080/health` work on the machine? Firewall (section 8)? |
| Everything stops after a while (laptop, Mac) | sleep or lid: see section 7 |
| Mac: nothing runs after a restart | Docker Desktop must start at sign-in, and someone must be signed in (section 7) |
| Changed `.env` but nothing changed | containers read `.env` when created: `docker compose up -d` |
