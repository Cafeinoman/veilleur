# ADR-0006 — Intégration NixOS dans une configuration d'hôte existante

- **Statut :** Accepté
- **Date :** 2026-11-15
- **Nature :** ADR rétrospective
- **Origine :** cahier ENF-01 à ENF-03b, §10 (2026-11-15, 3ᵉ ligne) ; PR #6

## Contexte

Veilleur doit s'installer sur un VPS dédié comme sur un serveur personnel qui porte déjà d'autres services
(frontal TLS, ntfy, sauvegarde, gestion des secrets).

## Options considérées

- Module autonome qui prend 80/443 et génère tout ; **module inerte tant qu'il est désactivé**, avec frontal TLS,
  ntfy, secrets et sauvegarde au choix de l'hôte ; image OCI (hors NixOS, moins déclarative).

## Décision

- Deux modules, `nixosModules.default` (`services.veilleur`) et `nixosModules.container`
  (`services.veilleur-container`), inertes tant que `enable = false` (`mkIf`).
- Frontal au choix (`proxy = "caddy"` ou `"external"`), ntfy intégré, externe ou aucun ; secrets fournis par
  l'hôte (chemins de fichiers, sops-nix ou agenix) ou générés dans le dossier d'état ; `backupPaths` et copie
  cohérente de la base ; `publicHost` dans les codes de jumelage ; assertions sur les conflits de ports et sur
  l'enregistrement AAAA en mode conteneur.
- La configuration de l'hôte s'évalue sur n'importe quelle machine (ENF-03).

## Conséquences

- Le détail de la réalisation (G5) est l'ADR-0020 ; le guide d'administration le documente.

## Sources

- `cahier_des_charges.MD` ENF-01 à ENF-03b, §10 ; `deploy/nixos/`, `docs/{en,fr}/admin-guide.md`, commit `0be164e`.
