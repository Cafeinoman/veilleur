# ADR-0012 — Service HTTP `/v1` : WSGI de la bibliothèque standard, limites, découverte des abonnements

- **Statut :** Accepté
- **Date :** 2026-11-17, complétée le 2026-11-18
- **Nature :** ADR rétrospective
- **Origine :** cahier §7.4, ES-06, ES-11, §10 (2026-11-17, cœur G2 ; 2026-11-18, réponses aux questions de G2) ; PR #3, #4

## Contexte

Le service est derrière un mandataire TLS, n'écoute que sur une adresse interne et sert une équipe. Les outils de
réception doivent découvrir leurs abonnements d'équipe.

## Options considérées

- Serveur : Gunicorn, Waitress (dépendances) ; **`wsgiref` à fils** (bibliothèque standard, charge faible, ENF-07).
- Découverte : abonnements d'équipe annoncés dans le code de jumelage (figés) ; **`GET /v1/subscriptions`**.
- Validation des paramètres : bibliothèque `jsonschema` (dépendance) ; **sous-ensemble de JSON Schema validé sans
  dépendance**.

## Décision

- Service WSGI sur `wsgiref` à fils ; routes et réponses du §7.4 ; erreurs `{"code", "message"}` sans détail
  interne ; `Cache-Control: no-store` partout ; corps limité à 1 Mo (`413`).
- Limite de débit : 120 requêtes par minute et par jumelage.
- `GET /v1/subscriptions` (2026-11-18) : abonnements vivants du jumelage (`uid`, origine, nom d'équipe, version),
  sans paramètres, authentifié par la clé propre au jumelage.
- Schémas des paramètres : sous-ensemble de JSON Schema (`veilleur.core.domain.schema`).
- Routage sur le chemin brut que signe le client ; `key_id` inconnu traité dans l'ordre du protocole §8.

## Conséquences

- Réserve R04 : les requêtes non authentifiées ne sont pas limitées et le corps est lu avant l'authentification.
- Réserves R17, R18 : surrogate isolé (500), `GET` avec corps accepté.

## Sources

- `cahier_des_charges.MD` §7.4, §10 ; `docs/en/protocol.md` §8, §9 ; `src/veilleur/apps/server/wsgi.py`, commit `0be164e`.
