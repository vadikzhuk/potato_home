# Remote access to the server

How to run commands on the server (the MacBook Air running potato_home) without
walking to it:

- **Part 1:** from another computer on the home network, with plain SSH.
- **Part 2:** from an Android phone, from anywhere, with Tailscale and an SSH app.

Part 2 builds on Part 1, so do Part 1 first.

The examples use the server's user `potato`, its name `Potatos-MacBook-Air.local`, and
the project folder `~/Dev/potato_home`. Change them if yours differ.

Everyday tasks (tickets, users, listings) don't need any of this: the Telegram bot
covers them. Remote access is for server work: updates, logs and restarts.

---

## Part 1: SSH from home

### On the server (the MacBook Air)

1. **Turn on SSH:** System Settings → General → Sharing → **Remote Login: on**.
   - Click the **ⓘ** next to it and set **Allow access for: Only these users: potato**.
   - The panel shows the address to connect to, e.g. `ssh potato@Potatos-MacBook-Air.local`.

2. **Keep it awake:** SSH can't reach a sleeping Mac. With the charger connected:
   ```bash
   sudo pmset -c sleep 0
   ```
   SETUP.md section 7 has the other "keep it running" settings: automatic login,
   closed lid, Docker Desktop at login.

3. **Firewall:** leave the firewall on, but **"Block all incoming connections" off**.
   Otherwise SSH (and the TV screen) can't get in.

### On your computer (another Mac)

1. **Create an SSH key**, if you don't have one yet (`ls ~/.ssh/id_ed25519.pub` finds nothing).
   Press Enter to accept the defaults:
   ```bash
   ssh-keygen -t ed25519
   ```

2. **Copy the key to the server.** It asks for potato's password this one time:
   ```bash
   ssh-copy-id potato@Potatos-MacBook-Air.local
   ```

3. **Give the server a short name:** add this to `~/.ssh/config` (create the file if it's missing):
   ```
   Host potato
     HostName Potatos-MacBook-Air.local
     User potato
   ```

4. **Connect:**
   ```bash
   ssh potato
   ```
   This is a normal terminal on the server, with your aliases from `~/.zshrc`:
   `estate runs`, `tk list`, `users list`, `dc ps`, `dc logs --tail 50 bot`…
   `exit` leaves it.

### One command without logging in

```bash
ssh -t potato 'zsh -lic "estate runs"'
```

- `-t` gives the command a terminal, which `docker compose exec` (and so every alias) needs.
- `zsh -lic` loads your PATH and aliases. Without it, `docker` and `estate` aren't found.

Updating the services in one line (see SETUP.md, "Updating"):

```bash
ssh -t potato 'zsh -lic "cd ~/Dev/potato_home && git pull && docker compose build && docker compose up -d"'
```

### Seeing the server's screen

In the same Sharing panel, turn on **Screen Sharing**. Then on your Mac, in Finder:
**Go → Connect to Server → `vnc://Potatos-MacBook-Air.local`**. This is handy for the
Docker Desktop window or a macOS dialog that wants a click.

---

## Part 2: from an Android phone, from anywhere

Away from home, the server can't be reached directly, and opening an SSH port on the
router would invite attacks. **Tailscale** (free for personal use) puts the phone and
the server into a small private network that works from anywhere, with nothing opened
on the router.

### 1. Tailscale on the server

1. Install **Tailscale** from the Mac App Store (or tailscale.com/download) and sign in
   with any account: Google, Apple, GitHub…
2. In its menu bar settings, turn on **Launch at login**, so it comes back after a restart.
3. At **login.tailscale.com → Machines**, open the server's **⋯** menu → **Disable key
   expiry**. Otherwise it asks you to sign in again every few months, and you'd lose
   access while away.
4. Note the server's Tailscale name on that page (e.g. `potatos-macbook-air`) or its
   address (starts with `100.`).

### 2. Tailscale on the phone

Install **Tailscale** from the Play Store, sign in with **the same account**, and
switch it on. The server appears in the app's device list. Leave Tailscale on whenever
you want to reach the server.

### 3. An SSH app on the phone

Install **Termius** (free) or **JuiceSSH** from the Play Store.

1. **Make a key in the app:** Termius has it under Keychain, JuiceSSH under Identities.
   Generate an **ed25519** key and copy its **public** part (one line starting with
   `ssh-ed25519`).
2. **Add that public key to the server.** From your Mac (Part 1 done):
   ```bash
   ssh potato 'cat >> ~/.ssh/authorized_keys'
   ```
   Paste the key, press Enter, then Ctrl+D. Or do it on the server itself: open
   `~/.ssh/authorized_keys` in a text editor and add the line at the end.
3. **Add the server as a host in the app:**
   - Address: the server's Tailscale name, or its `100.x.y.z` address
   - Username: `potato`
   - Key: the one from step 1
4. **Connect.** You're in the server's terminal, with the same commands as in Part 1.

**Typing on a phone is slow, so save commands as snippets** (Termius: Snippets;
JuiceSSH: Snippets in the connection's menu). Useful ones:

| Snippet | Command |
|---|---|
| Status | `cd ~/Dev/potato_home && docker compose ps` |
| Update | `cd ~/Dev/potato_home && git pull && docker compose build && docker compose up -d` |
| Bot log | `cd ~/Dev/potato_home && docker compose logs --tail 50 bot` |
| Estate fetches | `estate runs` |
| Restart the screen | `cd ~/Dev/potato_home && docker compose restart screen` |

---

## Safer: keys only, no passwords

Once logging in with a key works from every device you use, turn off SSH passwords on
the server. Then a stolen or guessed password can't log in over SSH.

1. Keep one SSH session open, just in case.
2. On the server:
   ```bash
   sudo nano /etc/ssh/sshd_config.d/100-keys-only.conf
   ```
   with these two lines:
   ```
   PasswordAuthentication no
   KbdInteractiveAuthentication no
   ```
3. macOS uses it from the next connection on. **Test a new connection** (from the Mac
   and the phone) before closing the open session.

To undo, delete that file.

And never forward port 22 (SSH) on the router. With Tailscale it's not needed.

---

## When it doesn't work

| What you see | What it usually means |
|---|---|
| `Connection refused` | Remote Login is off on the server |
| `Operation timed out` / no answer | the server is asleep or off; away from home: Tailscale is off on the phone or the server |
| `Could not resolve hostname` | at home: try the server's IP address (Remote Login panel) instead of the `.local` name; away: use the Tailscale name or `100.` address |
| `Permission denied (publickey…)` | the key isn't in the server's `~/.ssh/authorized_keys`, or that file has the wrong permissions: `chmod 600 ~/.ssh/authorized_keys` on the server |
| `docker: command not found` in a one-line command | add `zsh -lic "…"` around the command (see Part 1) |
| `the input device is not a TTY` | add `-t` to `ssh` |
| `REMOTE HOST IDENTIFICATION HAS CHANGED` | the server was reinstalled or the name now points elsewhere. If you know why: `ssh-keygen -R Potatos-MacBook-Air.local`, then connect again |
