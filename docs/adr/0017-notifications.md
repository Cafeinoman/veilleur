# ADR-0017 — Notifications par jumelage : `ntfy` et `webhook`, des comptes seulement

- **Statut :** Accepté
- **Date :** 2026-11-18
- **Nature :** ADR rétrospective
- **Origine :** cahier EF-52, EF-60, §10 (2026-11-18, G3) ; PR #4

## Contexte

Un membre doit savoir qu'un rapport l'attend, sans que la notification ne révèle de contenu à un tiers (ntfy public,
service de webhook).

## Options considérées

- Une notification pour toute l'équipe (révèle l'activité des autres) ; **une par jumelage**, sur un sujet aléatoire.
- Sujet dérivé du `key_id` (devinable) ; **sujet tiré au jumelage** (migration `0002`) et donné dans le code.

## Décision

- Notifications par jumelage, avec les comptes de ce jumelage seulement (rapports, éléments nouveaux, sources en
  panne ; plus de deux jours de panne signalés).
- `ntfy` : adresse de publication, adresse publique https, jetons dans des fichiers.
- `webhook` : corps JSON avec `sent_at`, en-tête `X-Veilleur-Signature: sha256=…`, clé dans un fichier ou générée
  dans `webhook.key`.
- Un greffon notificateur installé est utilisé.

## Conséquences

- Réserve R06 : le corps du webhook contient le sujet ntfy du jumelage, transmis au tiers qui reçoit le webhook.
- L'alerte `robots.txt` (ADR-0022) ajoute un compte à `RoundCounts`.

## Sources

- `src/veilleur/adapters/notifiers/__init__.py`, migration `0002_notification_topic.sql`, commit `0be164e`.
