# ADR-0016 — Filtre `regex` sur le moteur RE2

- **Statut :** Accepté
- **Date :** 2026-11-18 (décision de l'utilisateur après deux passages du vérificateur de G3)
- **Nature :** ADR rétrospective
- **Origine :** cahier §10 (2026-11-18, filtre `regex`) ; `plan.md` G3 ; PR #4

## Contexte

Un motif fourni par un outil de réception ne doit pas pouvoir bloquer le tour (retour arrière catastrophique).

## Options considérées

- `re` avec analyse statique des motifs (commit `0b30d8a`, « successive competing repetitions ») : abandonnée, faute
  de garantie ; `re` avec délai par motif (impossible proprement dans un fil Python) ; **RE2** (`google-re2`,
  BSD-3), recherche linéaire dans la taille du texte.

## Décision

- Moteur RE2, dépendance d'exécution ; syntaxe RE2 : ni références arrière ni assertions avant/arrière (refusées à
  la réception) ; `\w`, `\d`, `\b` limités à l'ASCII (`\pL` pour toute lettre).
- Empaquetage Nix par les *wheels* de `uv.lock` (ADR-0020).

## Conséquences

- Réserve R13 : certains motifs coûtent jusqu'à ≈ 4 s par champ de 20 000 caractères ; cache des motifs compilés
  sans borne. Réserve R17 : le schéma de `pattern` n'annonce pas la syntaxe RE2.

## Sources

- `cahier_des_charges.MD` §10 ; `plan.md` G3 ; commits `0b30d8a`, `4b48b9b`.
