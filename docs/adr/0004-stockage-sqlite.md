# ADR-0004 — Stockage SQLite en mode WAL, migrations SQL numérotées

- **Statut :** Accepté
- **Date :** 2026-11-15 (cahier version 1), précisée le 2026-11-17 (G2)
- **Nature :** ADR rétrospective
- **Origine :** cahier §7.2, EF-72 ; §10 (2026-11-18, compléments de G2 confirmés) ; PR #3

## Contexte

Une équipe, quelques centaines d'abonnements (ENF-07), deux processus (service HTTP et tour périodique, EF-71),
aucun administrateur de base de données.

## Options considérées

- **SQLite** (bibliothèque standard, un fichier, sauvegarde par l'API `backup`) ; PostgreSQL (service de plus à
  installer, sauvegarder, mettre à jour) ; fichiers JSON (pas de transactions entre deux processus).

## Décision

- SQLite en mode WAL ; migrations numérotées en SQL, appliquées à l'ouverture **après une sauvegarde** de la base
  (EF-72) ; une connexion par processus, usage sérialisé par un verrou dans le service.
- Tables : `pairing`, `collector_grant`, `subscription`, `source_status` (une ligne par collecte mutualisée), `item`,
  `reported`, `package`, `job`, `event` (journal d'administration). Migration `0002` : sujet de notification par
  jumelage (ADR-0017).
- Cache des requêtes conditionnelles dans une base à part, `cache/http.db` du dossier d'état (ADR-0014).

## Conséquences

- Les évolutions (avertissements DV-05, alertes `robots.txt`, expiration DV-06) passent par des migrations `0003` et
  suivantes, sauvegarde comprise.
- Le fichier `veilleur.db` est créé avec le masque du processus : 0644 hors systemd (réserve R08, atténuée par le
  dossier d'état en 0700 et `UMask=0077`).

## Sources

- `cahier_des_charges.MD` §7.2 ; `src/veilleur/adapters/sqlite/` (migrations `0001`, `0002`), commit `0be164e`.
