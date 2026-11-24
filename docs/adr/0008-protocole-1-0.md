# ADR-0008 — Protocole 1.0 : formats, ordre des contrôles, lecteur strict

- **Statut :** Accepté
- **Date :** 2026-11-17
- **Nature :** ADR rétrospective
- **Origine :** cahier ES-02 à ES-07, ES-13, §7.3, §10 (2026-11-17, 1ʳᵉ ligne) ; PR #2 (7 passages du vérificateur)

## Contexte

Des outils de réception écrits par d'autres doivent lire les paquets à partir de la seule spécification. Les passages
du vérificateur de G1 ont montré que toute latitude du lecteur (JSON laxiste, zip permissif) ouvre une faille.

## Options considérées

- Lire les archives avec `zipfile` de la bibliothèque standard ; **lecteur zip propre et restreint** (commit
  `31d0683`) : `zipfile` accepte Zip64, descripteurs de données et divergences entre en-têtes locaux et répertoire
  central.
- JSON : `json.loads` tel quel ; **JSON strict** (ni membre en double, ni `NaN`).
- Identifiants : UUID ; **`key_id` de 8 octets et `uid` de 16 octets en hexadécimal**.

## Décision

- `key_id` de 8 octets et `uid` de 16 octets en hexadécimal ; en-tête d'enveloppe de 30 octets portant `uid`,
  numéro et genre en clair, données associées = en-tête entier ; clé d'authentification propre au jumelage pour les
  requêtes hors abonnement ; un `state` ou `history` porte le numéro du dernier paquet dont il tient compte ; corps de
  `PUT` scellé avec pour numéro la version de base (0 à la création).
- Ordre des contrôles du lecteur et codes d'erreur fixés par la spécification ; JSON strict ; archive zip
  restreinte (ni Zip64, ni descripteur de données, en-têtes locaux identiques au répertoire central), lue par la
  bibliothèque elle-même.
- Après une rotation adoptée, l'outil de réception ne fait plus confiance à l'ancienne clé.
- 7ᵉ passage (commit `a48c755`) : clés publiques d'ordre faible refusées. Ce correctif n'a pas été revu (réserve R01).
- Une version mineure `1.x` n'ajoute que des membres facultatifs, que les anciens lecteurs ignorent.

## Conséquences

- Toute modification du protocole met à jour la spécification normative (anglais), sa traduction et les vecteurs.
- Les évolutions de 0.2.0 ne changent pas le protocole (ADR-0027) ; un ajout au manifeste serait une version 1.1.

## Sources

- `docs/en/protocol.md` (normatif), `protocol/vectors/`, `plan.md` G1 et ses réserves, commit `0be164e`.
