# Veilleur — déploiement (résumé)

> Résumé de l'existant (lot G5, ADR-0006 et ADR-0020). La référence est le guide d'administration,
> `docs/en/admin-guide.md` (anglais) et `docs/fr/admin-guide.md` (français) ; ce document ne le recopie pas.

## 1. Ce qui existe

| Élément | Où | Référence |
|---|---|---|
| Paquet et environnement Python (uv2nix, *wheels* de `uv.lock`), `x86_64-linux` et `aarch64-linux` | `flake.nix`, `deploy/nixos/python.nix` | ENF-02, ADR-0020 |
| Module de service `services.veilleur` (`nixosModules.default`) : service, minuterie du tour, durcissement, frontal `caddy` ou `external`, ntfy intégré/externe/aucun, secrets par chemins ou générés, `backupPaths`, copie cohérente | `deploy/nixos/module.nix`, `ports.nix` | ENF-01, ENF-03b, ENF-04 |
| Module conteneur `services.veilleur-container` (`nixosModules.container`) : `systemd-nspawn` à utilisateurs privés, réseau privé, pare-feu `nftables` sortant, `memoryMax` | `deploy/nixos/container.nix` | ENF-01 |
| Exemples : intégration dans un hôte existant, VPS dédié | `deploy/nixos/examples/` | ENF-03, ENF-03b |
| Repli pour les autres distributions : unités systemd, `Caddyfile`, extrait ntfy | `deploy/systemd/` | ENF-05 |
| Tests en VM et d'évaluation | `deploy/nixos/tests/`, `nix flake check` | ENF-06 |
| Version verrouillée : `github:Cafeinoman/veilleur/<étiquette>` | guide, §« installation » | ENF-03 |
| Sauvegarde, mise à jour, retour arrière | guide, sections dédiées | ENF-08 |

Accès : le service n'écoute que sur une adresse interne ; le frontal TLS (Caddy ou celui de l'hôte) le publie. Le
choix d'exposer le service sur Internet ou seulement sur un réseau privé (Tailscale) revient à l'administrateur ;
le guide traite les deux.

## 2. Ce que la reprise change

- **Configuration** (J9-L3, J10-L2) : nouvelles sections `[http]` (`robots`, `host_quota`, `host_interval`) et
  `[http.hosts."<hôte>"]` (`quota`, `interval`, `robots`) dans le fichier de configuration du serveur, transmises par
  le module comme les autres réglages. Bornes contrôlées au chargement (`invalid_config`).
- **Migrations** `0003` (avertissements, alertes `robots.txt`) et `0004` (expiration) : appliquées à l'ouverture,
  après la sauvegarde automatique (EF-72). Retour arrière : restaurer la copie de `backups/` ou la copie cohérente
  avant de revenir à une étiquette antérieure, la base migrée n'étant pas lisible par une version plus ancienne
  [Probable].
- **Durée du tour** : `Crawl-delay` peut allonger le tour (voir `docs/RISKS.md`, risque 6) ; rien à régler dans
  l'unité.
- **Unité des jetons ntfy** durcie (J8-L4, R07).
- **Webhook** : le corps n'a plus le membre `topic`, remplacé par `pairing` (J8-L4, D11).
- **Guide d'administration** (deux langues) : politique `robots.txt` et responsabilité de l'administrateur (J9-L3),
  limites par hôte (J10-L2), bloc de frontal ntfy complété (J13-L5).

Rien d'autre n'est reconçu : modules, conteneur, secrets et sauvegarde restent ceux de G5.

## 3. Vérifications laissées à l'utilisateur

- Émission réelle d'un certificat Let's Encrypt et exécution sur `aarch64-linux` (R23) : la CI ne peut pas les faire.

## Sources

- `flake.nix`, `deploy/`, `docs/{en,fr}/admin-guide.md`, `plan.md` G5, commit `0be164e`, consultés le 2026-11-19.
