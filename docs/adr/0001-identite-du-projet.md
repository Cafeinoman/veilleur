# ADR-0001 — Identité du projet : nom, licence, langues, hébergement

- **Statut :** Accepté
- **Date :** 2026-11-15, complétée le 2026-11-18 (G6)
- **Nature :** ADR rétrospective (décision antérieure au standard `/architecte`, reconstituée le 2026-11-19)
- **Origine :** cahier §10 (2026-11-15, 1ʳᵉ ligne ; 2026-11-18, réponses aux questions de G6), §9 ; PR #1, #7

## Contexte

Veilleur est un serveur de veille auto-hébergé destiné à de petites équipes, publié dès le départ. Il fallait un nom
libre, une licence compatible avec un usage par des administrations et associations européennes, une langue de
travail et un hébergement public avec intégration continue.

## Options considérées

- Licence : EUPL-1.2 ; AGPL-3.0 ; MIT ou Apache-2.0. [Suppose] L'EUPL a été préférée pour sa validité dans les
  langues de l'Union et sa compatibilité déclarée avec la GPL et l'AGPL ; une licence permissive aurait permis une
  reprise fermée du service.
- Langues : anglais seul ; français seul ; **bilingue** (code en anglais, textes lus par une personne en français et
  en anglais).
- Hébergement : GitHub ; une forge auto-hébergée. [Suppose] GitHub a été retenu pour Actions, Dependabot et le
  signalement privé des failles.
- Nom : vérifié libre sur PyPI le 2026-11-15 ; recherche de marque faite à l'INPI seulement (G6). Un projet homonyme
  (`veilleur.app`, agent d'astreinte) existe ; il ne vise pas le même usage.

## Décision

- Nom **Veilleur** ; licence **EUPL-1.2** (en-tête `# SPDX-License-Identifier: EUPL-1.2` sur chaque fichier Python) ;
  projet **bilingue** français et anglais ; hébergement **GitHub** (`Cafeinoman/veilleur`), dépôt public.
- 2026-11-18 : le nom **Veilleur** est conservé, aucun dépôt n'ayant été trouvé à l'INPI.

## Conséquences

- Toute dépendance a une licence compatible avec l'EUPL-1.2 (voir ADR-0003).
- Tout texte lu par une personne existe en deux langues (ADR-0005), la documentation aussi (`docs/en/`, `docs/fr/`).
- Recherche de marque incomplète (TMview, WIPO non consultés) : réserve R24, action de l'utilisateur.

## Sources

- `cahier_des_charges.MD` §9, §10 (commit `e355ab0`), consulté le 2026-11-19.
- `plan.md`, G6 (vérification du nom sur PyPI et à l'INPI).
