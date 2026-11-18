# Administration guide

This guide covers installing, running, backing up and updating a Veilleur server. Examples use reserved names (`watch.example.org`): replace them with yours.

## 1. Choosing an installation

| Installation | For | Module |
|---|---|---|
| Dedicated VPS | a machine that only runs Veilleur | `nixosModules.default` (`services.veilleur`) |
| Isolated container | a host that runs other services, with the strongest separation | `nixosModules.container` (`services.veilleur-container`) |
| Service on an existing host | a host that already has a TLS front end | `nixosModules.default` with `proxy = "external"` |
| Other Linux distributions | no NixOS | `deploy/systemd/` (§10) |

Both modules do nothing while `enable = false`: a host can import them unconditionally.

## 2. Choosing `publicHost`

`publicHost` is written into every pairing code. **Changing it later means pairing every member again**, so choose it with care:

- prefer a **name** to an IP address, even a free dynamic DNS name: the name survives a change of machine or provider;
- an IP address is accepted, but the certificate then depends on what Caddy can obtain for an address: check that a receiving tool accepts it before you hand out codes;
- in **container mode**, ports are forwarded in IPv4 only: the name must have **no AAAA record**, or Let's Encrypt and IPv6 clients will fail. The module refuses to build until you confirm this with `noAaaaRecord = true`.

## 3. Installing on a VPS

`deploy/nixos/examples/vps/` holds a complete example. Copy it, then:

1. replace the file systems and boot loader in `configuration.nix` with the output of `nixos-generate-config`;
2. point the DNS records of `publicHost` (and of `ntfy.host`, if you set one) at the machine;
3. set the tag of the `veilleur` input in `flake.nix`, then deploy:

```bash
nixos-rebuild switch --flake .#veilleur
```

Caddy obtains the certificates on first use; ports 80 and 443 must be reachable. Without `ntfy.host`, ntfy is served on port 8443 of `publicHost`.

## 4. Installing in a container

```nix
{
  imports = [ inputs.veilleur.nixosModules.container ];

  services.veilleur-container = {
    enable = true;
    publicHost = "watch.example.org";
    noAaaaRecord = true;
    externalInterface = "eth0";
    acmeEmail = "admin@example.org";
    memoryMax = "1G";
  };
}
```

The container runs with private users and a private network. From it, only the public Internet can be reached: neither the host, nor private networks, nor the Tailscale range (100.64.0.0/10), and port 25 is closed. It uses public DNS resolvers (`nameservers`), since it cannot reach the host's.

## 5. Integrating into an existing host

`deploy/nixos/examples/host-module.nix` loads Veilleur at a pinned version and reads its settings from a separate file. Without that file the module stays inert, so the host configuration evaluates on any machine.

Load Veilleur in one of these ways:

- as a flake input, locked in the host's `flake.lock`: `inputs.veilleur.url = "github:Cafeinoman/veilleur/<tag>"`;
- with `builtins.getFlake "github:Cafeinoman/veilleur/<tag>?narHash=<hash>"`; `nix flake metadata github:Cafeinoman/veilleur/<tag>` prints the hash;
- for a host without access to GitHub, from an archive you dropped there yourself: `tarball+file:///path/veilleur.tar.gz?narHash=<hash>`.

### Behind the host's reverse proxy

With `proxy = "external"`, Veilleur only listens on `listenAddress` (default `127.0.0.1:8470`). Add one of these blocks to your front end.

Caddy:

```caddyfile
watch.example.org {
	reverse_proxy 127.0.0.1:8470 {
		header_up -X-Forwarded-For
	}
}
```

nginx:

```nginx
server {
    listen 443 ssl;
    server_name watch.example.org;
    # ssl_certificate and ssl_certificate_key: as for your other sites.
    access_log off;
    client_max_body_size 2m;

    location / {
        # No path after the port: requests are signed over the exact path.
        proxy_pass http://127.0.0.1:8470;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For "";
    }
}
```

**Keep access logs off** for this site: members' addresses must not be written down. In container mode, use `containerAddress` (default `10.233.50.2`) instead of `127.0.0.1`.

The built-in ntfy server behind an external proxy needs `ntfy.publicUrl`, and a block of the same form towards `127.0.0.1:2586`.

## 6. Notifications and secrets

`ntfy.mode` selects the notification server:

- `builtin` (default): a ntfy server refuses anonymous clients; its accounts and tokens are drawn once, in `/var/lib/veilleur-ntfy`;
- `external`: an existing server, with `ntfy.url`, `ntfy.publicUrl`, and optionally `ntfy.tokenFile` and `ntfy.clientTokenFile`;
- `none`: no notification.

Secrets are never written into the Nix configuration. Give **paths** to files managed by sops-nix or agenix (`ntfy.tokenFile`, `ntfy.clientTokenFile`, `webhook.keyFile`):

- with `services.veilleur`, the files must be readable by the user `veilleur`;
- with `services.veilleur-container`, they stay on the host, owned by root, and reach the container as systemd credentials.

Without `webhook.keyFile`, the webhook key is generated in the state directory.

## 7. Daily administration

`veilleur-admin` runs the `veilleur` command as the service's user, as root on the host, in both modes:

```bash
veilleur-admin pairing new --label "desk 3"   # shows the code once
veilleur-admin pairing list
veilleur-admin pairing revoke "desk 3"
veilleur-admin sources                        # state of the collections
veilleur-admin round                          # run a round now
veilleur-admin notify --test
```

A label is a marker such as "desk 3", never a person's name. Hand the pairing code over by a safe channel: it holds a secret.

Rounds run according to `roundSchedule` (daily by default). Team subscriptions are declared in `subscriptions`, with the fields of the `[[subscriptions]]` tables of the configuration file.

Plugins are Python packages built for Python 3.12 and listed in `plugins`; nothing is installed at run time.

## 8. Backup and restore

What must be saved: the database, the server's signing key and rotation statement, the webhook key, and the state of the built-in ntfy server.

`veilleur-snapshot.service` writes a consistent copy of the state to `/var/lib/veilleur/snapshot`. The read-only option `backupPaths` lists the paths to save. Start the service **before** the backup:

```nix
services.restic.backups.daily = {
  paths = config.services.veilleur.backupPaths;
  backupPrepareCommand = "systemctl start veilleur-snapshot.service";
  # repository, passwordFile, timerConfig: as for your other backups.
};
```

In container mode, use `services.veilleur-container.backupPaths` and `veilleur-container-snapshot.service`. Alternatively, `snapshotSchedule` refreshes the copy on a schedule.

**The backup holds the server's private key**: encrypt it.

To restore, with the saved copy in `/root/restore`:

```bash
systemctl stop veilleur.service veilleur-round.timer
rm -f /var/lib/veilleur/veilleur.db-wal /var/lib/veilleur/veilleur.db-shm
install -o veilleur -g veilleur -m 600 /root/restore/* /var/lib/veilleur/
systemctl start veilleur.service veilleur-round.timer
```

## 9. Updating and rolling back

1. Make a fresh copy: `systemctl start veilleur-snapshot.service`, and save it.
2. Change the tag (and `narHash`, if you use one), then run `nixos-rebuild switch`.
3. Check with `veilleur-admin info` and `veilleur-admin sources`.

The database is migrated when it is opened, after an automatic backup in `/var/lib/veilleur/backups`.

To roll back, run `nixos-rebuild switch --rollback`. **If the update migrated the database, also restore the copy made before it** (§8): an older version is not meant to read a newer schema.

## 10. Other Linux distributions

`deploy/systemd/` provides the units, a `Caddyfile`, an ntfy excerpt and an example configuration. The code and its environment belong to root:

```bash
sudo useradd --system --home-dir /var/lib/veilleur --shell /usr/sbin/nologin veilleur
sudo git clone --branch <tag> https://github.com/Cafeinoman/veilleur.git /opt/veilleur/src
cd /opt/veilleur/src
sudo UV_PROJECT_ENVIRONMENT=/opt/veilleur/env uv sync --locked --no-dev --no-editable
sudo install -m 755 deploy/systemd/veilleur-snapshot.sh /opt/veilleur/
sudo install -m 644 deploy/systemd/*.service deploy/systemd/*.timer /etc/systemd/system/
sudo install -D -m 644 deploy/systemd/config.toml /etc/veilleur/config.toml
sudo systemctl daemon-reload
sudo systemctl enable --now veilleur.service veilleur-round.timer
```

Adapt `/etc/veilleur/config.toml` and the `Caddyfile`, which deliberately has no access log. The snapshot needs the `sqlite3` command. Administration commands run as the service's user:

```bash
sudo -u veilleur /opt/veilleur/env/bin/veilleur pairing new --label "desk 3"
```

For ntfy, start from `deploy/systemd/ntfy-server.yml`, then create one account that publishes and one that reads:

```bash
sudo ntfy user add veilleur-publish
sudo ntfy access veilleur-publish '*' write-only
sudo ntfy token add veilleur-publish
sudo ntfy user add veilleur-read
sudo ntfy access veilleur-read '*' read-only
sudo ntfy token add veilleur-read
```

Write the two tokens to the files named in `/etc/veilleur/config.toml`, readable by the user `veilleur` only.
