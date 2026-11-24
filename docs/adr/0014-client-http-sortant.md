# ADR-0014 — Client HTTP sortant : garde SSRF, politesse, limites, cache

- **Statut :** Accepté ; la partie `robots.txt` est **révisée par l'ADR-0022** (proposée)
- **Date :** 2026-11-18
- **Nature :** ADR rétrospective
- **Origine :** cahier EF-06, ES-08, §10 (2026-11-15, garde SSRF ; 2026-11-18, G3) ; PR #4

## Contexte

Les collecteurs suivent des adresses choisies par l'administrateur ou, s'il l'autorise, par un outil de réception.
Le serveur ne doit pas devenir une sonde du réseau interne, ni un robot impoli.

## Options considérées

- `urllib.request` ou `requests` (résolution et connexion indissociables : rebinding DNS possible) ; **transport
  propre qui se connecte à l'adresse contrôlée**, sans seconde résolution.
- Nom dont une adresse est interne : choisir une adresse publique ; **refuser le nom**.
- `robots.txt` illisible : tout permettre ; **refuser** (RFC 9309, « complete disallow » pour un serveur injoignable).

## Décision

- Garde SSRF : refuse un nom dont **une seule** adresse résolue est interne (bouclage, privée, lien-local, CGNAT,
  multidiffusion, réservée ; IPv4 enfouie dans IPv6 : *mapped*, NAT64, 6to4 ; Teredo refusé), à chaque redirection.
- `robots.txt` lu une fois par jour et par origine, avec `urllib.robotparser` ; illisible (5xx) : refus
  `robots_unavailable` ; absent (4xx) : tout permis ; adresse interdite : refus `robots_disallowed`.
- Délai d'1 s et quota de 200 requêtes par hôte et par processus ; réponses de 5 Mo au plus après décompression,
  30 s, 5 redirections ; cache conditionnel dans `cache/http.db` ; codes de panne stables (`address_refused`,
  `http_<statut>`…) ; mode hors ligne (`offline = true`).
- `User-Agent: Veilleur/<version> (+<adresse du serveur>)`.
- Les notificateurs, réglés par l'administrateur, ne passent pas par la garde SSRF et ne suivent pas les
  redirections.

## Conséquences

- Écarts relevés à la reprise : `urllib.robotparser` applique la **première** règle qui correspond, pas la plus
  longue comme le veut RFC 9309 §2.2.2 [Certain : essai sous Python 3.12.13, `Disallow: /a` puis `Allow: /a/b`
  refuse `/a/b`] ; `Crawl-delay` et `Retry-After` sont ignorés ; le quota n'est jamais remis à zéro dans `serve`.
- Révisions : ADR-0022 (`robots.txt`), ADR-0025 (limites par hôte), ADR-0026 (`Crawl-delay`, `Retry-After`).
- Réserves : R05 (`304` sans contrôle du type), R13 (lecture du corps jusqu'à ≈ 2× le délai), R18 (course dans `cut`).

## Sources

- `src/veilleur/adapters/http/client.py`, `guard.py`, `transport.py`, commit `0be164e`.
- RFC 9309, §2.2.2 et §2.3.1.4 — https://www.rfc-editor.org/rfc/rfc9309.html, consulté le 2026-11-19.
