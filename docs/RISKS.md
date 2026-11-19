# Veilleur — risques

> Classés par probabilité × impact (1 faible, 2 moyen, 3 fort). Chaque risque a un plan de repli.

| # | Risque | P | I | P×I | Atténuation | Repli |
|---|---|---|---|---|---|---|
| 1 | **Changement de politique `robots.txt` mal reçu** : un site ou un utilisateur lit « Veilleur ignore `robots.txt` » ; un administrateur passe outre une opposition à la fouille sans le savoir | 2 | 3 | 6 | alerte au premier passage outre ; notes de version en tête ; guide qui renvoie la responsabilité à l'administrateur ; `enforce` d'un seul réglage ; `User-Agent` honnête avec l'adresse du serveur | changer le défaut en `enforce` (une ligne et une note de version) ; le mécanisme d'alerte reste utile |
| 2 | **Perte d'une décision ou d'une réserve** à la reprise | 2 | 3 | 6 | `docs/REPRISE.md` ; `tests/test_pilot_documents.py` (identifiants, ADR, réserves, `xfail`) ; relecture du vérificateur en J7-L1 | l'historique git garde `cahier_des_charges.MD` et `plan.md` intégralement (étiquette `v0.1.0`) |
| 3 | **Rupture de l'API des greffons** pendant la réorganisation ou les ajouts DV, qui casse `veilleur-marches` | 2 | 3 | 6 | surface publique figée par `tests/test_plugin_api.py` (J7-L3) avant tout ajout ; ajouts seulement avec défaut ; chemins d'import inchangés ; S6 | alias de compatibilité et `DeprecationWarning` pendant une version mineure (ADR-0028) |
| 4 | **Fuite d'adresse collectée** (paramètres d'abonnement) dans l'alerte, les journaux ou la notification | 2 | 3 | 6 | l'alerte ne porte que l'hôte, le collecteur, la collecte et la règle ; test S2 avec jeton unique sur toutes les sorties | retirer la règle de l'alerte si elle s'avère porter des paramètres ; correctif de sécurité |
| 5 | **Volume de lots** (26 lots, chacun une session et un passage du vérificateur) irréaliste pour un développeur seul | 3 | 2 | 6 | ordre par valeur ; J13 et J14 explicitement COULD ; lots J7 courts | couper J13 et J14 ; regrouper des réserves P3 dans les lots qui touchent le même code |
| 6 | **Tours très longs** avec `Crawl-delay` (jusqu'à 60 s × 200 requêtes ≈ 3 h 20 par hôte) ; chevauchement de deux tours | 2 | 2 | 4 | plafond de 60 s ; quota par hôte ; [Probable] le service du tour est `Type=oneshot`, une minuterie ne relance pas une unité encore active | réduire le plafond ; budget de durée par collecte (code `round_budget_exceeded`) |
| 7 | **Revue R01 qui trouve un défaut du protocole** (clés d'ordre faible) | 1 | 3 | 3 | lot J8-L1 en tête du jalon de sécurité ; tests écrits depuis la spécification | correctif 0.1.1 ; si le format change, protocole 1.1 avec vecteurs |
| 8 | **Divergence de l'analyseur `robots.txt` propre** avec la pratique (Google, RFC 9309) | 2 | 1 | 2 | exemples de la RFC ; test différentiel contre Protego (D8) | utiliser Protego en exécution pour la décision et garder l'analyseur propre pour nommer la règle |
| 9 | **CI plus lente ou fragile** avec `nix develop` ; contrôles requis de `main` à mettre à jour à la main | 2 | 1 | 2 | nouveau travail ajouté sans toucher aux contrôles requis (D3) | retirer le travail `just test` de la CI et garder `just test` en local |
| 10 | **Sauts majeurs Dependabot** (#8, #9) qui cassent la CI | 2 | 1 | 2 | lot dédié J14-L2 ; actions fixées par empreinte | rester sur les versions actuelles, fermer les PR |
| 11 | **Sessions éphémères vues comme un contournement** par un site | 1 | 2 | 2 | aucun défi résolu ; pas de champ `password` ; cookies liés à l'hôte ; `User-Agent` honnête ; quotas | désactiver les sessions par hôte (`[http.hosts]`) ; retirer la fonction |
| 12 | **Exception de fouille perdue** pour un administrateur qui passe outre une opposition | 2 | 2 | 4 | guide d'administration (CGU, `robots.txt`, métadonnées) ; alerte ; `enforce` | l'administrateur retire la source ou passe l'hôte en `enforce` |
| 13 | **Lecture juridique erronée** dans l'ADR-0022 (textes lus par des sources secondaires) | 2 | 1 | 2 | affirmations étiquetées [Probable] ; ce n'est pas un avis juridique ; décision laissée à l'administrateur | relire EUR-Lex et Légifrance directement avant de publier 0.2.0 ; corriger le guide |

## Sources

- `docs/adr/0022-politique-robots-txt.md` et ses sources ; `deploy/nixos/module.nix` (`Type = "oneshot"`), commit
  `0be164e`, consultés le 2026-11-19.
