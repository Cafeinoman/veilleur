# ADR-0021 — Publication et distribution : étiquette et release GitHub, pas de PyPI

- **Statut :** Accepté
- **Date :** 2026-11-18
- **Nature :** ADR rétrospective
- **Origine :** cahier §10 (2026-11-18, publication G6 ; réponses aux questions de G6) ; PR #7, #10

## Contexte

Première version publique, alpha. Il fallait un numéro de version, un canal de distribution et un contrôle des
secrets sur tout l'historique.

## Options considérées

- Versions indépendantes par paquet ; **un numéro commun** aux trois paquets.
- Distribution sur PyPI ; **par l'étiquette git et la release GitHub** (l'installation passe par le flake).
- `SECURITY.md` en deux fichiers ; **un seul fichier bilingue**, pour que GitHub le reconnaisse.

## Décision

- Les trois paquets (`veilleur`, `veilleur-protocol`, `veilleur-receive`) partagent le numéro de version, 0.1.0 au
  stade alpha.
- `gitleaks` lit tout l'historique ; seuls les vecteurs `protocol/vectors/*.json` sont exclus par `.gitleaks.toml`.
- Notes de version dans `docs/{en,fr}/release-notes.md` ; `SECURITY.md` bilingue en un seul fichier.
- Réponses de l'utilisateur : le nom **Veilleur** est conservé (ADR-0001) ; **pas de publication sur PyPI** : la
  0.1.0 est distribuée par l'étiquette `v0.1.0` et la release GitHub, marquée préversion.

## Conséquences

- Les versions suivantes suivent la même règle (ADR-0028 : 0.2.0 après DV-01 et la politique `robots.txt`).
- Réserves R22 (exclusion `.gitleaks.toml` dépendante du dossier de lancement), R24 (marque).

## Sources

- `docs/{en,fr}/release-notes.md`, `.gitleaks.toml`, `SECURITY.md` ; `plan.md` G6, commit `0be164e`.
