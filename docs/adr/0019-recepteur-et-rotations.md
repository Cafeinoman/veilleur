# ADR-0019 — Récepteur de référence et suivi des rotations de clé

- **Statut :** Accepté
- **Date :** 2026-11-18
- **Nature :** ADR rétrospective
- **Origine :** cahier EF-50, EF-51, ES-05, §10 (2026-11-18, G4) ; protocole §6.3 ; PR #5 (3 passages du vérificateur)

## Contexte

Il faut un outil de réception minimal pour prouver le protocole et servir d'exemple, et une règle pour qu'un membre
suive les rotations de la clé du serveur, y compris par dossier.

## Options considérées

- Récepteur dans le paquet serveur (dépendance inutile) ; **paquet autonome `veilleur-receive`**.
- Code de jumelage en argument (visible dans `ps` et l'historique) ; **lu au terminal ou sur l'entrée standard**.
- Membre absent pendant deux rotations et un trou purgé : chaîne complète de déclarations dans chaque `state`
  (format plus lourd) ; **limite admise**, rejumelage.

## Décision

- `veilleur-receive` (`receiver/`), qui ne dépend que de `veilleur-protocol`, avec son catalogue de traduction ;
  commandes `pair` et `pull --folder <dossier> [--from <dossier exporté>]` ; dépôt dans
  `<dossier>/<uid>/<numéro>-<genre>/`, réservé à l'utilisateur ; état dans un fichier en 600, refusé s'il est
  lisible par d'autres.
- Un trou de numérotation n'est accepté que couvert par un `state`.
- Après l'adoption d'une clé, un paquet encore signé par l'ancienne est remplacé par un `state` demandé au serveur ;
  pendant les 90 jours de la déclaration, `veilleur export` écrit ce `state` en plus des paquets signés par
  l'ancienne clé ; les paquets restent, pour suivre une chaîne de rotations sans rejumelage.
- **Limite admise** : un membre à qui il manque un paquet déjà purgé et qui a manqué deux rotations ou plus doit
  être rejumelé.

## Conséquences

- Réserves R01 (inscription de la limite non revue), R02, R03, R14, R15.

## Sources

- `docs/en/protocol.md` §6.3 ; `receiver/` ; `plan.md` G4, commit `0be164e`.
