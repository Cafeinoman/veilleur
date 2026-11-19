# ADR-0015 — Collecteurs et filtres fournis : `rss`, `json_api`, `page`, `keywords`, `dedup`

- **Statut :** Accepté
- **Date :** 2026-11-18
- **Nature :** ADR rétrospective
- **Origine :** cahier EF-02, EF-20, §10 (2026-11-18, G3) ; PR #4

## Contexte

Trois collecteurs génériques couvrent l'essentiel des sources ; ils lisent des contenus hostiles.

## Options considérées

- XML : `xml.etree` tel quel (entités, DTD) ; `defusedxml` (dépendance) ; **expat avec toute DTD refusée**.
- HTML : `lxml` ou BeautifulSoup (dépendances, surface native) ; **sous-ensemble de sélecteurs CSS sans dépendance**.
- `dedup` : dédoublonnage entre collectes successives ; **un élément par valeur de champs choisis, parmi les éléments
  de la collecte** (interprétation retenue de « dédoublonnage entre collectes »).

## Décision

- `rss` (RSS 2.0 et Atom), jamais une collecte complète : une entrée sortie du flux n'est pas disparue.
- `json_api` (chemin des éléments, champ clé, pagination simple).
- `page` : un élément par page, champs `content` (texte visible normalisé) et `title`, partie désignée par un
  sélecteur CSS du sous-ensemble.
- Filtres `keywords` (casse et accents au choix), `regex` (ADR-0016), `dedup` comme ci-dessus.

## Conséquences

- Réserves R17 (sélecteur de `page` non contrôlé à la réception ; virgule entre guillemets).

## Sources

- `src/veilleur/adapters/collectors/`, `src/veilleur/adapters/filters/__init__.py`, commit `0be164e`.
