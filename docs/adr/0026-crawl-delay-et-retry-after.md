# ADR-0026 — `Crawl-delay` et `Retry-After` (DV-04)

- **Statut :** Accepté
- **Date :** 2026-11-19
- **Exigences :** DV-04, EF-06 (révisée)

## Contexte

Le client lit `robots.txt` mais ignore `Crawl-delay`, ce qui contredit son engagement de politesse ; il ignore aussi
`Retry-After`. La limite de 30 s par requête compte aujourd'hui l'attente du délai par hôte : une attente longue
deviendrait un `timeout`.

## Options considérées

- `Crawl-delay` : `urllib.robotparser.crawl_delay()` [Certain : présent en 3.12] ; **analyseur propre de
  l'ADR-0022**, qui le lit avec le reste.
- Au-delà du plafond : appliquer le plafond en silence ; **échouer avec un code stable** (DV-04, critère 4).

## Décision

- Délai appliqué = max(intervalle de l'hôte, `Crawl-delay` du groupe `Veilleur`, sinon du groupe `*`). Une directive
  pour un autre agent n'est pas appliquée. Valeurs décimales admises ; une valeur invalide est ignorée.
- **Plafond : 60 s.** Au-delà, la requête échoue avec `crawl_delay_too_long`, sans attendre.
- `Crawl-delay` s'applique **quelle que soit la politique `robots.txt`** (`warn` ou `enforce`).
- **L'attente ne compte pas dans la limite de 30 s** : le délai de la requête court après l'attente imposée.
- `Retry-After` : sur une réponse `429` ou `503`, la requête échoue (`http_429`, `http_503`) et l'hôte n'est plus
  demandé pendant la durée indiquée, plafonnée à la fin du tour ; les requêtes suivantes vers cet hôte échouent avec
  le même code sans partir. Exigence ajoutée à EF-06 (D14) : la reprise relève que le client ne lit pas
  `Retry-After`, bien que le brief le compte dans « ce qui reste dû ».
- Les tests utilisent une horloge simulée (pas d'attente réelle).

## Conséquences

- Un tour peut durer bien plus longtemps : 200 requêtes à 15 s font 50 minutes pour un hôte. Le service du tour est
  `Type=oneshot` [Probable : sans limite de durée de démarrage par défaut], donc pas tué ; risque noté dans
  `docs/RISKS.md`.

## Sources

- `DEMANDES-VEILLEUR.md`, DV-04 ; `src/veilleur/adapters/http/client.py` (`_pace`), commit `0be164e`.
- RFC 9309, §2.2.4 (autres enregistrements) — https://www.rfc-editor.org/rfc/rfc9309.html, consulté le 2026-11-19.
