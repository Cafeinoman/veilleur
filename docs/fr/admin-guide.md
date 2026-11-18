# Guide d'administration

Ce guide couvre l'installation, l'exploitation, la sauvegarde et la mise à jour d'un serveur Veilleur. Les exemples emploient des noms réservés (`watch.example.org`) : remplacez-les par les vôtres.

## 1. Choisir une installation

| Installation | Pour | Module |
|---|---|---|
| VPS dédié | une machine qui ne fait tourner que Veilleur | `nixosModules.default` (`services.veilleur`) |
| Conteneur isolé | un hôte qui porte d'autres services, avec la séparation la plus forte | `nixosModules.container` (`services.veilleur-container`) |
| Service sur un hôte existant | un hôte qui a déjà un frontal TLS | `nixosModules.default` avec `proxy = "external"` |
| Autres distributions Linux | sans NixOS | `deploy/systemd/` (§10) |

Les deux modules ne font rien tant que `enable = false` : un hôte peut les importer sans condition.

## 2. Choisir `publicHost`

`publicHost` est inscrit dans chaque code de jumelage. **Le changer ensuite oblige à rejumeler tous les membres** : choisissez-le avec soin.

- préférez un **nom** à une adresse IP, même un nom gratuit à mise à jour dynamique : le nom survit à un changement de machine ou d'hébergeur ;
- une adresse IP est acceptée, mais le certificat dépend alors de ce que Caddy peut obtenir pour une adresse : vérifiez qu'un outil de réception l'accepte avant de distribuer des codes ;
- en **mode conteneur**, les ports sont redirigés en IPv4 seulement : le nom ne doit avoir **aucun enregistrement AAAA**, sinon Let's Encrypt et les clients IPv6 échouent. Le module refuse de se construire tant que vous ne le confirmez pas par `noAaaaRecord = true`.

## 3. Installer sur un VPS

`deploy/nixos/examples/vps/` contient un exemple complet. Copiez-le, puis :

1. remplacez les systèmes de fichiers et le chargeur d'amorçage de `configuration.nix` par le résultat de `nixos-generate-config` ;
2. faites pointer les enregistrements DNS de `publicHost` (et de `ntfy.host`, si vous en donnez un) vers la machine ;
3. fixez l'étiquette de l'entrée `veilleur` dans `flake.nix`, puis déployez :

```bash
nixos-rebuild switch --flake .#veilleur
```

Caddy obtient les certificats à la première utilisation ; les ports 80 et 443 doivent être joignables. Sans `ntfy.host`, ntfy est servi sur le port 8443 de `publicHost`.

## 4. Installer en conteneur

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

Le conteneur tourne avec des utilisateurs privés et un réseau privé. Depuis lui, seul l'Internet public est joignable : ni l'hôte, ni les réseaux privés, ni la plage Tailscale (100.64.0.0/10), et le port 25 est fermé. Il emploie des résolveurs DNS publics (`nameservers`), puisqu'il ne peut pas joindre ceux de l'hôte.

## 5. Intégrer à un hôte existant

`deploy/nixos/examples/host-module.nix` charge Veilleur à une version verrouillée et lit ses réglages dans un fichier à part. Sans ce fichier, le module reste inerte : la configuration de l'hôte s'évalue donc sur n'importe quelle machine.

Chargez Veilleur de l'une de ces façons :

- en entrée de flake, verrouillée dans le `flake.lock` de l'hôte : `inputs.veilleur.url = "github:Cafeinoman/veilleur/<étiquette>"` ;
- par `builtins.getFlake "github:Cafeinoman/veilleur/<étiquette>?narHash=<empreinte>"` ; `nix flake metadata github:Cafeinoman/veilleur/<étiquette>` donne l'empreinte ;
- pour un hôte sans accès à GitHub, depuis une archive déposée à la main : `tarball+file:///chemin/veilleur.tar.gz?narHash=<empreinte>`.

### Derrière le mandataire de l'hôte

Avec `proxy = "external"`, Veilleur n'écoute que sur `listenAddress` (par défaut `127.0.0.1:8470`). Ajoutez l'un de ces blocs à votre frontal.

Caddy :

```caddyfile
watch.example.org {
	reverse_proxy 127.0.0.1:8470 {
		header_up -X-Forwarded-For
	}
}
```

nginx :

```nginx
server {
    listen 443 ssl;
    server_name watch.example.org;
    # ssl_certificate et ssl_certificate_key : comme pour vos autres sites.
    access_log off;
    client_max_body_size 2m;

    location / {
        # Aucun chemin après le port : les requêtes sont signées sur le chemin exact.
        proxy_pass http://127.0.0.1:8470;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For "";
    }
}
```

**Gardez le journal d'accès désactivé** pour ce site : l'adresse des membres ne doit pas être écrite. En mode conteneur, employez `containerAddress` (par défaut `10.233.50.2`) au lieu de `127.0.0.1`.

Le ntfy intégré derrière un frontal externe demande `ntfy.publicUrl`, et un bloc de même forme vers `127.0.0.1:2586` (en mode conteneur, `containerAddress` sur le port 2586).

Les modules refusent une configuration qui déclare un port dont Veilleur a besoin : redirections (`networking.nat.forwardPorts`, `containers.<nom>.forwardPorts`), ports publiés par des conteneurs OCI et entrées `listen` explicites des hôtes virtuels nginx et Apache. Un port ouvert autrement ne peut pas être détecté à l'évaluation.

## 6. Notifications et secrets

`ntfy.mode` choisit le serveur de notification :

- `builtin` (par défaut) : un serveur ntfy qui refuse les clients anonymes ; ses comptes et jetons sont tirés une fois, dans `/var/lib/veilleur-ntfy` ;
- `external` : un serveur existant, avec `ntfy.url`, `ntfy.publicUrl` et, au besoin, `ntfy.tokenFile` et `ntfy.clientTokenFile` ;
- `none` : aucune notification.

Les secrets ne sont jamais écrits dans la configuration Nix. Donnez des **chemins** vers des fichiers gérés par sops-nix ou agenix (`ntfy.tokenFile`, `ntfy.clientTokenFile`, `webhook.keyFile`) :

- avec `services.veilleur`, les fichiers doivent être lisibles par l'utilisateur `veilleur` ;
- avec `services.veilleur-container`, ils restent sur l'hôte, propriété de root, et parviennent au conteneur comme identifiants systemd (*credentials*).

Sans `webhook.keyFile`, la clé du webhook est générée dans le dossier d'état.

## 7. Administration courante

`veilleur-admin` lance la commande `veilleur` sous l'utilisateur du service, en root sur l'hôte, dans les deux modes :

```bash
veilleur-admin pairing new --label "poste 3"   # affiche le code une seule fois
veilleur-admin pairing list
veilleur-admin pairing revoke "poste 3"
veilleur-admin sources                         # état des collectes
veilleur-admin round                           # lancer un tour maintenant
veilleur-admin notify --test
```

Un libellé est un repère comme « poste 3 », jamais un nom de personne. Remettez le code de jumelage par un canal sûr : il contient un secret.

Les tours suivent `roundSchedule` (quotidien par défaut). Les abonnements d'équipe se déclarent dans `subscriptions`, avec les champs des tables `[[subscriptions]]` du fichier de configuration.

Les greffons sont des paquets Python construits pour Python 3.12 et listés dans `plugins` ; rien n'est installé à l'exécution.

## 8. Sauvegarde et restauration

À sauvegarder : la base, la clé de signature du serveur et sa déclaration de rotation, la clé du webhook et l'état du ntfy intégré.

`veilleur-snapshot.service` écrit une copie cohérente de l'état dans `/var/lib/veilleur/snapshot`. L'option en lecture seule `backupPaths` liste les chemins à sauvegarder. Lancez le service **avant** la sauvegarde :

```nix
services.restic.backups.daily = {
  paths = config.services.veilleur.backupPaths;
  backupPrepareCommand = "systemctl start veilleur-snapshot.service";
  # repository, passwordFile, timerConfig : comme pour vos autres sauvegardes.
};
```

En mode conteneur, employez `services.veilleur-container.backupPaths` et `veilleur-container-snapshot.service`. Sinon, `snapshotSchedule` renouvelle la copie à heure fixe.

**La sauvegarde contient la clé privée du serveur** : chiffrez-la.

Pour restaurer, avec la copie sauvegardée dans `/root/restore` :

```bash
systemctl stop veilleur.service veilleur-round.timer
rm -f /var/lib/veilleur/veilleur.db-wal /var/lib/veilleur/veilleur.db-shm
install -o veilleur -g veilleur -m 600 /root/restore/* /var/lib/veilleur/
systemctl start veilleur.service veilleur-round.timer
```

## 9. Mise à jour et retour arrière

1. Faites une copie récente : `systemctl start veilleur-snapshot.service`, et sauvegardez-la.
2. Changez l'étiquette (et le `narHash`, si vous en employez un), puis lancez `nixos-rebuild switch`.
3. Contrôlez avec `veilleur-admin info` et `veilleur-admin sources`.

La base est migrée à son ouverture, après une sauvegarde automatique dans `/var/lib/veilleur/backups`.

Pour revenir en arrière, lancez `nixos-rebuild switch --rollback`. **Si la mise à jour a migré la base, restaurez aussi la copie faite avant elle** (§8) : une version plus ancienne n'est pas prévue pour lire un schéma plus récent.

## 10. Autres distributions Linux

`deploy/systemd/` fournit les unités, un `Caddyfile`, un extrait de configuration ntfy et un exemple de configuration. Le code et son environnement appartiennent à root :

```bash
sudo useradd --system --home-dir /var/lib/veilleur --shell /usr/sbin/nologin veilleur
sudo git clone --branch <étiquette> https://github.com/Cafeinoman/veilleur.git /opt/veilleur/src
cd /opt/veilleur/src
sudo UV_PROJECT_ENVIRONMENT=/opt/veilleur/env uv sync --locked --no-dev --no-editable
sudo install -m 755 deploy/systemd/veilleur-snapshot.sh /opt/veilleur/
sudo install -m 644 deploy/systemd/*.service deploy/systemd/*.timer /etc/systemd/system/
sudo install -D -m 644 deploy/systemd/config.toml /etc/veilleur/config.toml
sudo systemctl daemon-reload
sudo systemctl enable --now veilleur.service veilleur-round.timer
```

Adaptez `/etc/veilleur/config.toml` et le `Caddyfile`, qui n'a volontairement aucun journal d'accès. La copie cohérente demande la commande `sqlite3`. Les commandes d'administration se lancent sous l'utilisateur du service :

```bash
sudo -u veilleur /opt/veilleur/env/bin/veilleur pairing new --label "poste 3"
```

Pour ntfy, partez de `deploy/systemd/ntfy-server.yml`, puis créez un compte qui publie et un compte qui lit :

```bash
sudo ntfy user add veilleur-publish
sudo ntfy access veilleur-publish '*' write-only
sudo ntfy token add veilleur-publish
sudo ntfy user add veilleur-read
sudo ntfy access veilleur-read '*' read-only
sudo ntfy token add veilleur-read
```

Écrivez les deux jetons dans les fichiers nommés par `/etc/veilleur/config.toml`, lisibles par le seul utilisateur `veilleur`.
