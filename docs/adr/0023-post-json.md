# ADR-0023 — Requêtes POST à corps JSON (DV-01)

- **Statut :** Proposé
- **Date :** 2026-11-19
- **Exigences :** DV-01, EF-06, ES-08, ES-09

## Contexte

Certaines API publiques de recherche n'acceptent que le POST, la requête étant trop riche pour une adresse. Le port
`HttpClient` n'a que `get`. Demande ferme du greffon `veilleur-marches`.

## Options considérées

1. Méthode générique `request(method, url, body, headers)` : ouvre la porte aux en-têtes du greffon, aux méthodes
   d'écriture et aux corps arbitraires.
2. **`post_json(url, body, *, accept=())`** : un seul usage, corps sérialisé par le client.
3. Laisser le greffon ouvrir ses propres connexions : contraire à EF-06.

## Décision

Option 2.

- Signature : `post_json(url: str, body: JSON, *, accept: Sequence[str] = ()) -> HttpResponse`, où `body` est un
  objet JSON (dict, list, str, int, float fini, bool, None). Le client le sérialise lui-même (JSON strict : ni `NaN`
  ni infini, UTF-8, séparateurs compacts) et envoie `Content-Type: application/json`. Aucun en-tête fourni par le
  greffon.
- Corps de **1 Mo au plus** après sérialisation : au-delà, `request_too_large` avant toute résolution ni connexion.
- Mêmes étapes que `get` : adresse contrôlée, politique `robots.txt` (ADR-0022), quota et délai par hôte
  (ADR-0025, ADR-0026), résolution puis garde SSRF, plafonds de taille et de durée, contrôle du type de contenu.
- Redirections : `301`, `302`, `303` **refusées sans nouvelle requête** (`redirect_refused`), pour ne jamais changer
  le POST en GET ; `307` et `308` suivies **une fois au plus**, vers le **même hôte** (même schéma, hôte et port),
  en refaisant tous les contrôles ; sinon `redirect_refused`.
- **Pas de cache conditionnel** ; une réponse `304` est une panne (`bad_response`).
- Mode hors ligne : `network_unavailable`, comme `get`.
- Le corps n'apparaît jamais dans un journal, une exception ou un événement ; l'adresse non plus (ES-09).
- Le POST compte dans le quota de l'hôte.

## Conséquences

- Ajout au port `HttpClient` : compatible pour les greffons qui l'appellent (ADR-0028), mais un client écrit hors
  du dépôt (fausses implémentations des tests d'un greffon) devra l'ajouter. Un greffon qui l'utilise exige
  Veilleur ≥ 0.2.0 ; il le vérifie par `veilleur.__version__` (ADR-0028).
- Nouveaux codes stables `request_too_large`, `redirect_refused`, traduits.
- Critère 5 de DV-01 réécrit selon l'ADR-0022 : en `warn`, la requête part et l'alerte est émise ; en `enforce`,
  `robots_disallowed`.

## Sources

- `~/projects/veilleur-marches/docs/DEMANDES-VEILLEUR.md`, DV-01 (commit `4cccab5`), consulté le 2026-11-19.
- RFC 9110, §15.4 (les clients peuvent changer POST en GET sur 301, 302 ; 303 l'impose ; 307 et 308 l'interdisent)
  — https://www.rfc-editor.org/rfc/rfc9110.html#section-15.4 [Certain, de mémoire ; non relu le 2026-11-19].
