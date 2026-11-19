# ADR-0025 — Limites réglables par hôte et remise à zéro du quota (DV-03)

- **Statut :** Proposé
- **Date :** 2026-11-19
- **Exigences :** DV-03 ; réserve R26 (quota jamais remis à zéro dans `serve`)

## Contexte

Le quota de 200 requêtes et le délai d'1 s par hôte sont fixés dans le code (`Limits`), construits sans réglage dans
`apps/server/context.py`. Le quota est compté **par processus** : un tour (processus neuf) le remet à zéro, le
service `serve` jamais. DV-03 parle d'un quota « par tour » : écart entre la demande et le code.

## Options considérées

- Réglage par collecteur ou par abonnement : accessible aux outils de réception, refusé (DV-03 : réservé à
  l'administrateur).
- **Section de configuration par hôte**, dans le fichier TOML du serveur et l'option de réglages du module NixOS.
- Jokers (`*.example.org`) : [Suppose] écartés pour la première version (un hôte = un nom exact) ; ajout possible.

## Décision

- Format :

  ```toml
  [http]
  robots = "warn"          # ADR-0022
  host_quota = 200         # défaut de l'instance
  host_interval = 1.0

  [http.hosts."data.example.org"]
  quota = 1000
  interval = 1.0
  robots = "enforce"       # facultatif
  ```

- Hôte : nom exact, en minuscules, IDNA ; une adresse IP est admise telle qu'écrite.
- **Intervalle minimal imposé : 1,0 s** ; **quota maximal imposé : 10 000** [Suppose] ; une valeur hors bornes est
  refusée au chargement de la configuration (`invalid_config`, avec le nom du membre).
- **Quota par tour** : le compteur est remis à zéro au début de chaque tour (`veilleur round`, minuterie) et de
  chaque tâche du fil de travail de `serve` qui collecte. La limite de débit de l'API (120 requêtes par minute et
  par jumelage) borne déjà le nombre de tâches.
- Le réglage n'a d'effet ni sur la garde SSRF ni sur un autre hôte ; `Crawl-delay` peut allonger l'intervalle
  (ADR-0026), jamais le raccourcir.

## Conséquences

- La réserve G3 « quota jamais remis à zéro dans `serve` » (R26) est levée par le même lot.
- Le module NixOS transmet ces réglages par son fichier de configuration ; le guide d'administration les documente.

## Sources

- `DEMANDES-VEILLEUR.md`, DV-03 ; `src/veilleur/adapters/http/client.py` (`Limits`) ;
  `src/veilleur/apps/server/context.py`, commit `0be164e`.
