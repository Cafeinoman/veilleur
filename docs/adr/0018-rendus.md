# ADR-0018 — Rendus `markdown` et `html` : toute valeur collectée est hostile

- **Statut :** Accepté
- **Date :** 2026-11-18
- **Nature :** ADR rétrospective
- **Origine :** cahier EF-43, §10 (2026-11-18, G4) ; PR #5

## Contexte

Les rendus sont ouverts par des personnes dans un navigateur ou un éditeur ; les valeurs viennent de sources
quelconques.

## Options considérées

- Moteur de gabarits (Jinja2 : dépendance, échappement à bien configurer) ; **rendu écrit à la main**, échappement
  propre à chaque format.

## Décision

- Caractères de contrôle et de direction retirés ; échappement propre au format ; lien pour les seules adresses
  `http(s)` ; une adresse portant un caractère de contrôle ou de direction reste du texte ; politique de sécurité du
  contenu dans la page HTML, sans JavaScript ni ressource externe.
- Valeurs abrégées à 4 000 caractères ; rendu plafonné à 2 millions de caractères d'éléments ; `items.jsonl` garde
  tout ; un paquet trop gros avec ses rendus est scellé sans eux.

## Conséquences

- Réserve R19 : U+061C non retiré ; adresses hors du plafond ; texte de lien non abrégé.

## Sources

- `src/veilleur/adapters/renderers/__init__.py`, commit `0be164e`.
