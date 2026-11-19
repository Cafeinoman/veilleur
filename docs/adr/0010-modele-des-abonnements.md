# ADR-0010 — Modèle des abonnements et des jumelages

- **Statut :** Accepté
- **Date :** 2026-11-17
- **Nature :** ADR rétrospective
- **Origine :** cahier EF-10, EF-11, EF-14, EF-60 à EF-62, §10 (2026-11-17, cœur G2) ; PR #3

## Contexte

Les clés d'un abonnement dérivent du secret de jumelage (ES-02). Un abonnement d'équipe peut viser plusieurs membres ;
une requête rejouée dans la fenêtre de 5 minutes ne doit pas recréer un abonnement supprimé.

## Options considérées

- Un abonnement partagé entre jumelages (clés communes : impossible sans secret commun) ; **un abonnement par
  jumelage**, un abonnement d'équipe existant N fois.
- Suppression physique (un `PUT` rejoué recrée l'abonnement) ; **pierre tombale** dont la version continue de croître.
- Espace d'`uid` global ; **espace par jumelage** (`404` pour l'abonnement d'un autre).

## Décision

- Un abonnement appartient à **un** jumelage ; un abonnement d'équipe rattaché à N jumelages existe N fois, chacun
  avec un `uid` tiré à sa création.
- Un `uid` supprimé reste en pierre tombale, sa version croît encore et il n'est jamais réutilisé
  (`409 subscription_deleted`) : création et suppression rejouées sont sans effet.
- Collecteurs qui ne suivent pas d'adresse du client : autorisés par défaut ; les autres (`rss`, `page`, `json_api`)
  refusés par défaut, réglables par `veilleur collectors allow|deny|default` (EF-11).
- Abonnements d'équipe déclarés en TOML ou par le module NixOS (EF-10), synchronisés à chaque tour.

## Conséquences

- Réserves ouvertes : R10 (déclaration d'équipe cassée), R11 (faute dans `pairings`), R16 (doublon après
  suppression et redéclaration dans la même seconde).

## Sources

- `cahier_des_charges.MD` §5.2, §5.7, §10 ; `docs/en/protocol.md` §9 ; `plan.md` G2, commit `0be164e`.
