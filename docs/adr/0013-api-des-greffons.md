# ADR-0013 — API des greffons : *entry points*, schémas, contrôles complémentaires

- **Statut :** Accepté
- **Date :** 2026-11-17, complétée le 2026-11-18 (G3)
- **Nature :** ADR rétrospective
- **Origine :** cahier EF-01, EF-11, EF-12, EF-20, EF-43, EF-52, §10 (2026-11-17 ; 2026-11-18, G3) ; PR #3, #4

## Contexte

Une source propre à un domaine s'ajoute par un greffon maintenu hors du dépôt (projet générique). Le greffon
`veilleur-marches` dépend aujourd'hui de cette API.

## Options considérées

- Découverte : configuration listant des chemins Python ; **groupes d'*entry points*** `veilleur.collectors`,
  `veilleur.filters`, `veilleur.renderers`, `veilleur.notifiers`.
- Contrat : classes de base à hériter ; **protocoles structurels** (`typing.Protocol`) et objets de données gelés.

## Décision

- Un collecteur publie `name`, `schema`, `follows_client_urls` et `collect(params, since, http)`, qui rend
  `Collected` ou une suite de `CollectedItem` ; il n'accède au réseau que par `http` (EF-06) et signale une panne
  par `CollectorError` avec un code stable.
- `check_params` (facultatif) contrôle à la réception ce qu'un schéma ne peut exprimer ; `select` (facultatif) donne
  à un filtre tous les éléments à la fois.
- Un notificateur installé est utilisé ; un notificateur reçoit des comptes (`RoundCounts`), jamais de contenu.
- Surface utilisée par les greffons : `veilleur.core.ports.plugins`, `veilleur.core.ports.http`,
  `veilleur.core.domain.model` (`Collected`, `CollectedItem`), `veilleur.core.domain.errors` (`CollectorError`).

## Conséquences

- Cette surface n'est déclarée nulle part comme publique : l'ADR-0028 la fixe et la protège pendant la
  réorganisation et les évolutions DV-01 à DV-06.
- Un greffon s'exécute dans le processus du serveur : EF-06 est un contrat, pas un bac à sable.

## Sources

- `src/veilleur/core/ports/plugins.py`, `src/veilleur/core/ports/http.py`, `examples/veilleur-example-collector/`,
  `docs/en/writing-a-collector.md`, commit `0be164e`.
