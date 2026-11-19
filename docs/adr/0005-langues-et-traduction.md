# ADR-0005 — Langues : textes sources en anglais, un catalogue gettext français

- **Statut :** Accepté
- **Date :** 2026-11-15
- **Nature :** ADR rétrospective
- **Origine :** cahier §5.9 (EF-80 à EF-82), §9, §10 (2026-11-15, 4ᵉ ligne) ; PR #1

## Contexte

Le projet est bilingue (ADR-0001). Il fallait choisir la langue des textes sources, l'outil de traduction et la
façon de traduire la ligne de commande.

## Options considérées

- Textes sources en français, catalogue anglais ; **textes sources en anglais, catalogue français** ; deux jeux de
  textes écrits à la main (dérive assurée).
- Ligne de commande : `click` ou `typer` (dépendance de plus) ; **`argparse`**, dont les textes standard sont
  traduits par le catalogue.

## Décision

- Textes sources en anglais, passés par `_()` / `ngettext()` de `veilleur.i18n`, paramètres nommés ; un seul
  catalogue gettext (français) ; le récepteur a son propre catalogue (ADR-0019).
- Langue d'un processus : `--lang`, puis `VEILLEUR_LANG`, puis la langue du système, à défaut l'anglais ; langue
  d'un rapport : celle de l'abonnement ; langue d'une erreur d'API : `Accept-Language`, sinon celle du serveur
  (2026-11-17).
- Codes d'erreur et identifiants de formats : identifiants anglais stables, jamais traduits.
- `argparse` ; ses textes standard sont traduits, même avant que la langue soit fixée (commit `6d58e9e`).

## Conséquences

- Les tests refusent un message non traduit, approximatif ou obsolète, et un `.mo` périmé ; la documentation a les
  mêmes fichiers dans les deux langues (`tests/test_repository.py`).
- Réserve R21 : noms de valeur d'`argparse` encore en anglais dans l'aide française.

## Sources

- `cahier_des_charges.MD` §5.9, §10 ; `docs/{en,fr}/translating.md` ; `tools/i18n.py`, commit `0be164e`.
