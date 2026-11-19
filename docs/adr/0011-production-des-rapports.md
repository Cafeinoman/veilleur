# ADR-0011 — Production des rapports : ce qui a été rapporté fait référence

- **Statut :** Accepté
- **Date :** 2026-11-17
- **Nature :** ADR rétrospective
- **Origine :** cahier EF-30 à EF-45, §7.5, §10 (2026-11-17, cœur G2 ; 2026-11-18, G3 pour `rss`) ; PR #3

## Contexte

Les collectes sont mutualisées (EF-04) mais chaque abonnement a ses filtres et sa périodicité. Un `delta` doit
rester juste quand les changements s'accumulent entre deux échéances, et un `state` doit être cohérent avec les
`delta` déjà livrés.

## Options considérées

- Comparer l'état courant à l'état du tour précédent (faux pour une périodicité quotidienne ou hebdomadaire) ;
  **comparer à ce que chaque abonnement a rapporté en dernier** (table `reported`).
- Construire un `state` à partir de l'état courant ; **à partir de ce qui a été rapporté**.

## Décision

- Chaque abonnement garde ce qu'il a rapporté en dernier ; un `delta` compare à cela les éléments courants filtrés ;
  les changements s'accumulent jusqu'à l'échéance ; un élément qu'un filtre ne retient plus devient `gone`.
- Le premier `state` est produit dès la première collecte réussie, même sans élément.
- Un `state` ou un `history` demandé est construit à partir de ce qui a été rapporté.
- Un élément ne disparaît qu'après une collecte complète réussie (EF-31) ; un flux `rss` n'est jamais complet.
- Paquets numérotés sans trou, gardés 90 jours (`410` ensuite) ; rapport vide non produit.

## Conséquences

- L'expiration demandée par DV-06 doit retirer un élément de `reported` sans le publier comme `gone` (ADR-0027).
- Réserve R15 (export et rotations) touche la façon de combler un trou par un `state`.

## Sources

- `cahier_des_charges.MD` §5.4, §5.5, §7.5, §10 ; `src/veilleur/core/services/reports.py`, commit `0be164e`.
