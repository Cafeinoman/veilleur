# Veilleur — plan de travail

> Ce qu'il reste à faire, lot par lot. Le **quoi** est dans `docs/SPEC.md`, les décisions dans `docs/adr/`, les
> questions ouvertes dans `docs/DECISIONS.md`. Ce plan est lu par `/livrer` et par le vérificateur : chaque critère
> d'acceptation doit pouvoir être vérifié par un tiers sans autre contexte que ce plan, la spécification et les ADR.

## Règles du plan

- Un lot = un identifiant `J<n>-L<m>`, une branche `claude/<identifiant>-<sujet>` créée depuis `main` à jour, une
  session ; clos par `/clear` puis `/livrer`, qui ouvre la PR et passe le statut à `fait`.
- Tant qu'une PR attend sa fusion, le lot suivant peut avancer dans une nouvelle session s'il n'en dépend pas ; sinon
  sa branche part de la branche en attente, et la PR le dit.
- Un test `xfail` strict passe en vert quand sa réserve est levée : le lot retire le marqueur, jamais le test.
- Un lot qui change un comportement documenté met à jour `docs/SPEC.md` d'abord, puis la documentation dans les deux
  langues.
- Les jalons J7 et J8 ne changent aucun comportement visible des greffons ; J9 et J10 forment la version 0.2.0,
  J11 et J12 la 0.3.0 (ADR-0028).
- **Coupes possibles** si l'effort dépasse ce qui est utile : J13 (exactitude) et J14 (confort) sont COULD ; J12-L2
  (DV-06) est COULD.

## Historique

Lots livrés avant la reprise au standard (pilotés par l'ancien `plan.md`). Non redécrits.

| Lot d'origine | Objet | Étiquette / PR | Statut |
|---|---|---|---|
| G0-R | Dépôt git, environnement, contrôles, dépôt GitHub publié, protection de `main` | `g0`, PR #1 | fait |
| G1 | Protocole 1.0 et `veilleur-protocol`, vecteurs, seconde implémentation, modèle de menace | `g1`, PR #2 | fait, avec réserves |
| G2 | Cœur, stockage SQLite, administration, service HTTP `/v1` | `g2`, PR #3 | fait, avec réserves |
| G3 | Client HTTP sûr, collecteurs, filtres, notificateurs | `g3`, PR #4 | fait, avec réserves |
| G4 | Rendus, récepteur de référence | `g4`, PR #5 | fait, avec réserves |
| G5 | Déploiement NixOS et repli systemd | `g5`, PR #6 | fait, avec réserves |
| G6 | Publication 0.1.0 | `g6`, `v0.1.0`, PR #7, #10 | fait, avec réserves |
| — | Fin de l'enchaînement des lots sans confirmation | PR #11 | fait |

## J7 — Mise au standard (aucun changement de comportement)

Produit : le même Veilleur 0.1.0, piloté par `docs/`, contrôlé par `just test`, avec une API des greffons figée par un
test.

### J7-L1 — Mise au standard du dépôt

- **Objectif.** Donner au dépôt les outils et les règles du standard commun, sans toucher au code.
- **Étapes.**
  1. `justfile` : `test` (dans cet ordre : `uv run --locked pytest`, `uv run --locked ruff check src tests tools protocol
     receiver`, `uv run --locked mypy`, `uv run --locked lint-imports`, `uv run --locked python tools/check_vectors.py`,
     `uv run --locked python tools/protocol_vectors.py --check`), `fmt` (`ruff format` puis `ruff check --fix`), `vm`
     (`nix flake check -L`) ; pas d'`env-up`/`env-down` (D4).
  2. `flake.nix` : `just` dans `devShells.default`.
  3. CI : nouveau travail « `just test` (nix develop) » qui lance `nix develop -c just test` ; la matrice uv et le
     travail Nix restent tels quels (D3).
  4. Surveillance de la charge de la CI (D3, ADR-0029) : `tools/ci_load.py`, recette `just ci-load`, flux planifié
     chaque semaine qui lance le script ; seuils 20 minutes et deux fois la matrice (D16).
  5. `CLAUDE.md` réécrit au format de `/nouveau-projet` : objet ; étiquettes de version seulement (D6) ; documents
     qui font foi (`docs/PLAN.md`, `docs/SPEC.md`, `docs/adr/`) ; commande de contrôle `just test` ; règle « un lot = un identifiant `J<n>-L<m>` de
     `docs/PLAN.md`, sur une branche `claude/<identifiant>-<sujet>` » ; questions ouvertes dans `docs/DECISIONS.md` ;
     règles propres conservées (généricité, architecture, langues et i18n, licence, sécurité, tests sans réseau,
     données, droits du jeton GitHub repris de l'ancien `plan.md` G0-R étape 0) ; règles communes non recopiées.
  6. `.claude/settings.json` : ajouter `Bash(just:*)`.
  7. `CONTRIBUTING.md` et `CONTRIBUTING.fr.md` : citer `just test` et `tools/check_vectors.py` (lève R22, premier point).
  8. `tests/test_pilot_documents.py` (voir `docs/TEST-STRATEGY.md` §4).
- **Critères d'acceptation.**
  1. `nix develop -c just test` réussit sur la branche ; `just --dry-run test` affiche les six commandes de l'étape 1.
  2. Un contrôle qui échoue (par exemple une erreur `ruff` introduite à la main) fait échouer `just test` avec un code
     de sortie non nul.
  3. `.github/workflows/ci.yml` contient un travail qui exécute `nix develop -c just test`, et les travaux existants
     gardent leur nom ; toute action ajoutée est fixée par empreinte de commit (`tests/test_repository.py` passe).
  4. `CLAUDE.md` nomme `docs/PLAN.md`, `docs/SPEC.md` et `docs/adr/` comme documents qui font foi, contient
     `just test` et la règle `J<n>-L<m>` / `claude/<identifiant>-<sujet>`, ne présente plus `cahier_des_charges.MD` ni
     `plan.md` comme documents qui font foi, et contient le tableau des droits du jeton GitHub.
  5. `tests/verif/test_g6_release.py::test_the_guide_lists_every_check_of_the_ci` passe sans marqueur `xfail`.
  6. `tests/test_pilot_documents.py` existe et passe ; il échoue si l'on retire un identifiant EF, ES ou ENF de
     `docs/SPEC.md`, un fichier d'ADR cité, une réserve `Rnn` de ce plan, ou si un `xfail` de `tests/verif/` n'est
     cité dans aucune réserve.
  7. Hors le marqueur retiré au critère 5, aucun fichier de test existant n'est modifié.
  8. `tools/ci_load.py` a ses tests (réponses de `gh` enregistrées, sans réseau) : code nul sous les seuils, non nul
     avec le nom du travail au-delà ; le flux planifié n'a que le droit `actions: read` et ses actions sont fixées
     par empreinte.
- **Références.** ADR-0029, ADR-0002 ; SPEC §9 ; `docs/REPRISE.md` §2.8, §2.10.
- **Risques.** `nix develop` en CI allonge la durée ; Python 3.12 seul dans ce travail (la matrice garde 3.13).
- **Effort.** M
- **Statut.** fait (réserves R27 à R31)

### J7-L2 — Retrait des anciens documents de pilotage

- **Objectif.** Faire de `docs/` la seule source, sans perdre une vérification existante.
- **Étapes.**
  1. Remplacer le contenu de `cahier_des_charges.MD` et de `plan.md` par un renvoi de quelques lignes vers
     `docs/SPEC.md`, `docs/adr/`, `docs/PLAN.md` et `docs/REPRISE.md`.
  2. Rediriger `tests/verif/test_design_follows_spec.py` vers `docs/SPEC.md` et
     `tests/verif/test_g6_release.py::test_the_specification_records_the_decisions_of_the_release` vers
     `docs/adr/0021-publication-et-distribution.md`, en ne changeant que le chemin lu (et le découpage par section pour
     le second). Le signaler dans la PR.
  3. `docs/{en,fr}/design.md` : introduction mise à jour (version 0.1.0 publiée, renvoi à la spécification) ; « the
     cahier » / « le cahier » remplacés par la spécification ; la feuille de route renvoie à `docs/PLAN.md` après G6.
  4. Docstrings et commentaires du code et des tests : « cahier » → « spec », identifiants inchangés.
  5. `tests/test_pilot_documents.py` prend `docs/REPRISE.md` (liste figée) pour référence au lieu du cahier.
- **Critères d'acceptation.**
  1. `cahier_des_charges.MD` et `plan.md` font moins de 15 lignes chacun et contiennent les chemins `docs/SPEC.md` et
     `docs/PLAN.md`.
  2. `just test` réussit.
  3. Dans `git diff main -- tests`, les seules lignes modifiées hors docstrings et commentaires sont celles qui
     désignent le fichier lu par les deux tests redirigés.
  4. `grep -rni "cahier" src tests tools protocol receiver deploy docs/en docs/fr` ne renvoie rien.
  5. `docs/en/design.md` et `docs/fr/design.md` ne contiennent plus « will be » / « sera » dans leur introduction ni
     « exist today » / « existe aujourd'hui », et gardent la même structure (`test_same_structure_in_both_languages`).
- **Références.** ADR-0029 ; `docs/REPRISE.md` §3 (E7, E8, E9).
- **Risques.** Affaiblir sans le voir un test redirigé : le critère 3 l'empêche.
- **Effort.** S
- **Statut.** fait (PR #14, réserves R32 à R34)

### J7-L3 — Surface de l'API des greffons et remise au propre du code

- **Objectif.** Figer l'API dont dépendent les greffons avant de l'étendre, et ranger les greffons fournis.
- **Étapes.**
  1. `tests/test_plugin_api.py` : surface publique de l'ADR-0028 (noms ; champs, ordre et défauts des objets de
     données ; méthodes des protocoles ; membres des énumérations `Kind` et `Change` ; groupes d'*entry points*).
  2. `adapters/filters`, `adapters/renderers`, `adapters/notifiers` découpés en un module par
     greffon (comme `adapters/collectors`), avec réexport depuis `__init__.py` (D5).
  3. `docs/{en,fr}/writing-a-collector.md` : liste de la surface publique et règle de compatibilité.
- **Critères d'acceptation.**
  1. `tests/test_plugin_api.py` passe, et échoue si l'on renomme un champ de `CollectedItem`, retire une méthode de
     `HttpClient` ou change l'ordre des champs de `Collected`.
  2. `veilleur.adapters.filters.KeywordsFilter`, `RegexFilter`, `DedupFilter`, `veilleur.adapters.renderers.MarkdownRenderer`,
     `HtmlRenderer`, `veilleur.adapters.notifiers.NtfyNotifier`, `WebhookNotifier` restent importables ; chaque
     *entry point* fourni charge une classe de même `__name__` qu'avant le lot.
  3. `git diff --stat main -- tests` ne montre que des fichiers ajoutés.
  4. `just test` réussit ; les quatre contrats `lint-imports` sont inchangés.
  5. Les deux guides d'écriture d'un collecteur listent les mêmes modules publics.
- **Références.** ADR-0028, ADR-0029, ADR-0013 ; SPEC §7.1.
- **Risques.** Un test de surface trop strict gêne les ajouts légitimes : il fige les noms et l'ordre, pas les
  docstrings.
- **Effort.** M (S sans le découpage)
- **Statut.** fait (PR #15, réserves R35 à R38)

## J8 — Sécurité (réserves P1)

Produit : Veilleur 0.1.x sans réserve de sécurité ouverte. À faire avant d'exposer un service public (DV-01).

### J8-L1 — Revue indépendante des correctifs jamais revus

- **Objectif.** Faire vérifier, à partir de la spécification seule, les trois diffs qu'aucun vérificateur n'a relus (R01).
- **Étapes.**
  1. Écrire `tests/verif/test_j8_l1_review.py` à partir de `docs/en/protocol.md` (§6.1, §6.3, §8, §10.1), du modèle
     de menace et de l'ADR-0019, **sans lire les diffs avant d'avoir écrit les tests** : clés publiques Ed25519 d'ordre
     faible refusées par la bibliothèque et par `tools/check_vectors.py` ; élément trop profond pour être haché écarté
     comme `bad_item` sans arrêter le tour ; limite admise des deux rotations décrite de la même façon dans
     `protocol.md` (en, fr), l'ADR-0019 et les raisons des `xfail` concernés.
  2. Lancer ces tests contre le code ; un écart bloquant est corrigé dans le lot, les autres deviennent des réserves.
- **Critères d'acceptation.**
  1. Le fichier de tests existe, cite pour chaque test le paragraphe de la spécification dont il vient, et passe (ou
     ses échecs sont des `xfail` stricts rattachés à une réserve nouvelle de ce plan).
  2. Au moins 8 clés publiques d'ordre faible connues (dont l'élément neutre et un point d'ordre 8) sont refusées par
     `veilleur_protocol` et par `tools/check_vectors.py`.
  3. Un collecteur qui rend un élément dont les champs sont imbriqués sur 10 000 niveaux donne l'état `bad_item` et
     les autres collectes du tour aboutissent.
  4. La PR liste les diffs revus (`383b9ca..a48c755`, `0e30a66`, `bdc6946`) et le verdict.
- **Références.** R01 ; ADR-0008, ADR-0019 ; SPEC ES-04, ES-05, EF-05.
- **Risques.** Le vérificateur de `/livrer` relit un lot dont le code est une revue : ses tests portent sur les
  mêmes diffs, ce qui fait deux regards indépendants.
- **Effort.** S
- **Statut.** à faire

### J8-L2 — Récepteur : signalement et secrets

- **Objectif.** Lever R02, R03 et R14 (même code, `veilleur-receive`).
- **Étapes.** Signaler un paquet forgé même couvert par un `state` ; ne jamais répéter un code de jumelage passé en
  argument ; refuser proprement un code non UTF-8.
- **Critères d'acceptation.**
  1. `tests/verif/test_g4_verif_pass3.py::test_a_forged_package_is_reported_even_when_a_state_covers_it`,
     `tests/verif/test_g4_verif.py::test_a_code_given_as_an_argument_is_not_repeated` et
     `::test_a_pairing_code_that_is_not_text_is_refused_cleanly` passent sans marqueur `xfail`.
  2. `veilleur-receive pair VEIL1:<code valide>` sort avec un code non nul, et ni stdout ni stderr ne contiennent une
     sous-chaîne de 16 caractères du code.
  3. Les messages ajoutés existent en français et en anglais (tests de traduction du récepteur).
- **Références.** R02, R03, R14 ; ADR-0019 ; SPEC ES-07, EF-60.
- **Risques.** Faible.
- **Effort.** M
- **Statut.** à faire

### J8-L3 — Service HTTP : requêtes non authentifiées, droits de la base

- **Objectif.** Lever R04 et R08.
- **Étapes.**
  1. Contrôler en-tête, date et `key_id` avant de lire le corps ; lire le corps seulement pour vérifier l'empreinte.
  2. Limiter les réponses `401` : au plus 300 par minute pour le processus (D12), au-delà `429 rate_limited`
     sans lecture du corps ; les requêtes authentifiées ne sont pas comptées.
  3. Créer `veilleur.db` (et ses fichiers WAL) en 0600 quel que soit le masque du processus.
- **Critères d'acceptation.**
  1. Une requête sans en-tête `Authorization`, ou avec un `key_id` inconnu, reçoit `401` sans que `wsgi.input` soit lu
     (test avec un flux qui lève s'il est lu).
  2. La 301ᵉ requête non authentifiée dans la même minute (horloge simulée) reçoit `429` ; une requête authentifiée
     valide envoyée ensuite reçoit sa réponse normale.
  3. Avec `umask 022`, `veilleur.db` est créé en mode 0600.
  4. L'ordre des contrôles du protocole §8 est inchangé (`tests/server/test_api.py` passe).
- **Références.** R04, R08 ; ADR-0012 ; SPEC ES-06, ES-10, ES-11 ; protocole §8.
- **Risques.** La limite globale permet à un attaquant de gêner les clients non authentifiés seulement, pas les autres.
- **Effort.** M
- **Statut.** à faire

### J8-L4 — Sorties du serveur : cache, webhook, unité des jetons

- **Objectif.** Lever R05, R06 et R07.
- **Étapes.**
  1. Une réponse `304` servie depuis le cache contrôle le type de contenu en cache contre `accept`.
  2. Le corps du webhook ne contient plus le sujet ntfy ; il identifie le jumelage par son `key_id` (D11) ; guide
     d'administration et notes de version dans les deux langues.
  3. L'unité qui tire les jetons ntfy reçoit le durcissement des autres unités (ENF-04), sans perdre son effet.
- **Critères d'acceptation.**
  1. `tests/verif/test_g3_verif.py::test_a_cached_answer_is_checked_against_the_expected_content_types` et
     `tests/verif/test_g5_verif.py::test_the_unit_that_draws_the_tokens_is_hardened` passent sans `xfail`.
  2. Le corps JSON d'un webhook envoyé par un tour n'a pas de membre `topic` et a un membre `pairing` égal au `key_id`
     du jumelage ; sa signature se vérifie avec la clé du webhook.
  3. Le test en VM d'installation complète (`nix flake check`) passe : les jetons ntfy sont tirés et le service publie.
- **Références.** R05, R06, R07 ; ADR-0014, ADR-0017, ADR-0020 ; SPEC ES-08, EF-52, ENF-04.
- **Risques.** Changement du corps du webhook : un récepteur de webhook existant qui lisait `topic` doit s'adapter ;
  annoncé dans les notes de version.
- **Effort.** M
- **Statut.** à faire

## J9 — Politique `robots.txt`, `Crawl-delay`, avertissements (première moitié de 0.2.0)

Produit : un Veilleur qui lit `robots.txt` selon RFC 9309, respecte `Crawl-delay` et `Retry-After`, passe outre
`robots.txt` avec alerte par défaut, et garde le respect strict au choix.

### J9-L1 — Analyseur `robots.txt` RFC 9309, `Crawl-delay`, `Retry-After`

- **Objectif.** Remplacer `urllib.robotparser`, appliquer DV-04 et `Retry-After`, sans changer la politique (toujours
  stricte dans ce lot).
- **Étapes.**
  1. Module `veilleur.adapters.http.robots` : analyse (groupes, agents insensibles à la casse, règle la plus longue,
     `Allow` gagne à égalité, `*`, `$`, encodage `%`, 500 Kio au plus), rend « permis ou non », la règle en cause et
     `Crawl-delay`.
  2. Protego en dépendance de développement (D8) et test différentiel sur un corpus de fichiers
     `robots.txt` et d'adresses.
  3. Délai par hôte = max(intervalle, `Crawl-delay`) ; plafond 60 s (`crawl_delay_too_long`) ; l'attente hors des 30 s.
  4. `Retry-After` sur `429` et `503` (secondes ou date HTTP), plafonné à la fin du processus.
  5. Un `robots.txt` illisible est mémorisé 1 heure (E3) ; docstring corrigée (E2).
- **Critères d'acceptation.**
  1. Avec `Disallow: /a` puis `Allow: /a/b` pour `*`, `/a/b` est permise et `/a/c` refusée (`robots_disallowed`).
  2. Les exemples de RFC 9309 §5 donnent le résultat attendu par la RFC.
  3. DV-04, critères 1 à 5 (SPEC §11), avec une horloge simulée.
  4. Après une réponse `429` avec `Retry-After: 120`, une requête vers le même hôte dans les 120 s échoue avec
     `http_429` sans qu'aucune requête ne parte ; après 120 s, elle part.
  5. Un `robots.txt` en `503` demandé deux fois en moins d'une heure n'est lu qu'une fois.
  6. Les tests existants du client HTTP passent sans modification.
- **Références.** ADR-0022 (point 1), ADR-0026 ; SPEC EF-06, DV-04, §7.6, §12 ; `docs/REPRISE.md` E1 à E4.
- **Risques.** Écarts d'interprétation de RFC 9309 : le test différentiel les montre.
- **Effort.** M
- **Statut.** à faire

### J9-L2 — Avertissements de collecte (DV-05) et portée de collecte

- **Objectif.** Donner aux collectes un canal d'avertissements, utilisé ensuite par l'alerte `robots.txt`.
- **Étapes.**
  1. `Collected.warnings` (champ final avec défaut) ; contrôle des codes (8 au plus, `bad_warning`).
  2. Migration `0003` : avertissements dans `source_status`.
  3. Port serveur `ServerHttp` et portée de collecte : le cœur appelle le collecteur dans la portée ; à la sortie,
     même après une exception, le client rend ses avertissements.
  4. `veilleur sources` affiche les codes, traduits s'ils sont connus.
  5. `tests/test_plugin_api.py` mis à jour pour l'ajout (champ final avec défaut), signalé dans la PR.
- **Critères d'acceptation.**
  1. DV-05, critères 1 à 3 (SPEC §11).
  2. Un code `"Budget Exceeded"` est écarté, l'état de la collecte porte `bad_warning`, la collecte réussit.
  3. Un collecteur qui lève une exception après avoir fait une requête voit quand même sa portée refermée (test avec
     un faux client qui compte les ouvertures et fermetures).
  4. Une base 0.1.0 est migrée, une sauvegarde est faite avant, et les collectes existantes gardent leur état.
  5. `Collected(items)` et `Collected(items, False)` restent valides.
- **Références.** ADR-0027 ; SPEC DV-05, EF-05, §7.2.
- **Risques.** Changement du port vu par le cœur : le port `HttpClient` des greffons ne doit pas changer.
- **Effort.** M
- **Statut.** à faire

### J9-L3 — Politique `warn`/`enforce` et alerte au premier passage outre

- **Objectif.** Livrer EF-06 révisée et EF-07.
- **Étapes.**
  1. Réglage `robots` dans `[http]` et `[http.hosts."<hôte>"]` (format de l'ADR-0025), défaut `warn`.
  2. Table des alertes émises (migration) ; événement `robots_ignored` ; avertissement `robots_ignored` ; compte
     `robots_ignored` dans `RoundCounts`, message `ntfy`, membre du webhook.
  3. Tests existants sur `robots_disallowed` et `robots_unavailable` rattachés au mode `enforce`, assertions
     inchangées, signalé dans la PR.
  4. Documentation en deux langues : README, guide d'administration (responsabilité de l'administrateur, CGU,
     opposition à la fouille, `robots = "enforce"`), guide d'écriture d'un collecteur, `design.md`, modèle de menace,
     notes de version (section « non publiée »).
- **Critères d'acceptation.**
  1. Sans réglage, une adresse interdite par `robots.txt` est demandée et ses éléments sont collectés.
  2. Deux tours successifs sur cette adresse produisent un seul événement `robots_ignored`, et une seule notification
     qui compte cette source.
  3. Après une modification de `robots.txt` qui interdit encore l'adresse, un nouvel événement est produit.
  4. Pour une adresse portant un jeton unique dans son chemin et dans sa requête, ce jeton n'apparaît ni dans les
     journaux capturés, ni dans le journal d'administration, ni dans la sortie de `veilleur sources`, ni dans le corps
     des notifications `ntfy` et `webhook`.
  5. Avec `robots = "enforce"` dans `[http]`, l'adresse est refusée avec `robots_disallowed` ; avec `robots = "warn"`
     pour cet hôte dans `[http.hosts]`, elle est collectée malgré `enforce` dans `[http]`, et inversement.
  6. En `warn`, un `robots.txt` absent (`404`) ou en `500` ne bloque pas la collecte et ne produit pas d'alerte.
  7. Une valeur `robots = "ignore"` est refusée au chargement (`invalid_config`).
  8. Le guide d'administration, dans les deux langues, contient `robots = "enforce"` et un paragraphe sur la
     responsabilité de l'administrateur ; les tests de parité de la documentation passent.
- **Références.** ADR-0022, ADR-0025, ADR-0027 ; SPEC EF-06, EF-07, EF-52, ES-09.
- **Risques.** Engagement public modifié (voir `docs/RISKS.md`, risque 1) ; fuite d'adresse dans l'alerte (critère 4).
- **Effort.** L
- **Statut.** à faire

## J10 — POST JSON, limites par hôte, version 0.2.0

Produit : Veilleur 0.2.0, avec lequel le greffon peut interroger une API de recherche en POST et lire un hôte en un tour.

### J10-L1 — Requêtes POST à corps JSON (DV-01)

- **Objectif.** Ajouter `post_json` au client HTTP.
- **Étapes.** Port `HttpClient` étendu ; client réseau et client hors ligne ; règles de redirection ; codes
  `request_too_large`, `redirect_refused` traduits ; guide d'écriture d'un collecteur ; test de surface mis à jour.
- **Critères d'acceptation.**
  1. DV-01, critères 1 à 7 (SPEC §11).
  2. Une réponse `307` vers le même hôte est suivie une fois, en POST, avec le même corps ; une seconde `307` est
     refusée (`redirect_refused`) ; une `308` vers un autre hôte est refusée sans requête.
  3. Une réponse `303` est refusée sans nouvelle requête.
  4. Un corps contenant `float("nan")` est refusé avant toute connexion.
  5. En mode hors ligne, `post_json` lève `network_unavailable`.
  6. Une réponse `304` à un POST est une panne `bad_response`, et le cache n'est jamais consulté ni rempli.
- **Références.** ADR-0023, ADR-0028 ; SPEC DV-01, ES-08, ES-09.
- **Risques.** Faible ; mêmes chemins que `get`.
- **Effort.** M
- **Statut.** à faire

### J10-L2 — Limites réglables par hôte (DV-03) et quota par tour (R26)

- **Objectif.** Rendre le quota et l'intervalle réglables par l'administrateur, et le quota remis à zéro par tour.
- **Étapes.** Section `[http]` et `[http.hosts]` de la configuration (bornes), passage au client ; remise à zéro au
  début de chaque tour et de chaque tâche du service ; guide d'administration.
- **Critères d'acceptation.**
  1. DV-03, critères 1 à 6 (SPEC §11).
  2. `veilleur config` affiche les réglages par hôte.
  3. Le module NixOS évalue avec un exemple de réglage par hôte (test d'évaluation).
- **Références.** ADR-0025 ; SPEC DV-03, §7.5, §7.6 ; R26.
- **Risques.** Faible.
- **Effort.** M
- **Statut.** à faire

### J10-L3 — Publication 0.2.0

- **Objectif.** Préparer la version 0.2.0.
- **Étapes.** Numéro 0.2.0 dans les trois paquets et `uv.lock` ; notes de version en deux langues, le changement de
  politique `robots.txt` en tête ; README ; exemples de déploiement qui citent l'étiquette `v0.2.0`.
- **Critères d'acceptation.**
  1. `tests/test_repository.py::test_the_three_packages_share_one_version` et
     `::test_the_current_version_has_release_notes_in_both_languages` passent avec 0.2.0.
  2. Le premier point de la section 0.2.0 des notes, dans chaque langue, parle de `robots.txt`.
  3. `just test` et `nix flake check` réussissent.
  4. L'étiquette n'est pas posée par le lot (D6).
- **Références.** ADR-0021, ADR-0028.
- **Risques.** Faible.
- **Effort.** S
- **Statut.** à faire

## J11 — Disponibilité du tour et du service (réserves P2)

Produit : un tour qui ne s'arrête pour aucune faute de greffon ou de déclaration, et des coûts bornés. Prérequis de
DV-02.

### J11-L1 — Garde-fous du tour

- **Objectif.** Lever R09, R10 et R11.
- **Critères d'acceptation.**
  1. `tests/verif/test_g2_core.py::test_lazy_collected_items_that_fail_do_not_stop_the_round`,
     `::test_collector_error_with_a_non_string_code_does_not_stop_the_round` et
     `tests/verif/test_g2_cli.py::test_a_broken_team_declaration_does_not_stop_the_other_subscriptions` passent sans
     `xfail`.
  2. Une déclaration d'équipe dont un jumelage de `pairings` est mal écrit ne supprime pas l'abonnement existant de
     ses autres jumelages ; un événement le signale.
  3. Un abonnement d'équipe dont le greffon est absent prend l'état `collector_missing` et `veilleur round` traite les
     autres.
- **Références.** R09, R10, R11 ; ADR-0010 ; SPEC EF-05, EF-10.
- **Risques.** Faible.
- **Effort.** M
- **Statut.** à faire

### J11-L2 — Rotation de clé suivie par le service

- **Objectif.** Lever R12.
- **Critères d'acceptation.**
  1. `tests/verif/test_g2_core.py::test_running_service_follows_a_key_rotation` et
     `::test_two_rotations_within_90_days_keep_receivers_following` passent sans `xfail`.
  2. Un paquet produit par `serve` après un `veilleur key rotate` lancé par un autre processus est signé par la
     nouvelle clé et porte la déclaration de rotation.
- **Références.** R12 ; ADR-0007, ADR-0019 ; SPEC ES-05 ; protocole §6.3.
- **Risques.** Touche le protocole si deux déclarations doivent voyager ensemble : alors version 1.1 (spécification,
  traduction, vecteurs).
- **Effort.** M
- **Statut.** à faire

### J11-L3 — Coûts bornés

- **Objectif.** Lever R13.
- **Critères d'acceptation.**
  1. `tests/verif/test_g3_pass3.py::test_the_compiled_pattern_cache_is_bounded` et
     `tests/verif/test_g4_verif.py::test_a_very_deep_answer_is_a_refusal` passent sans `xfail`.
  2. Un motif `regex` dont le programme RE2 dépasse la borne choisie est refusé à la réception (`invalid_params`) ; le
     plus lent des motifs acceptés d'un corpus de test met moins d'1 s sur un champ de 20 000 caractères.
  3. Au plus 4 tâches `history` en attente par jumelage (D12) ; la suivante reçoit `429`.
  4. Une réponse qui envoie son corps goutte à goutte est coupée au plus 1 s après la limite de 30 s.
- **Références.** R13 ; ADR-0016, ADR-0014 ; SPEC EF-20, ES-11, §7.5.
- **Risques.** Bornes trop basses qui refusent des motifs utiles : corpus de motifs réels dans les tests.
- **Effort.** L
- **Statut.** à faire

## J12 — Sessions éphémères et expiration (version 0.3.0)

Produit : Veilleur 0.3.0, avec lequel le greffon lit les sites publics à formulaire et borne la taille de ses `state`.

### J12-L1 — Sessions éphémères (DV-02)

- **Objectif.** Ajouter `http.session()` (ADR-0024).
- **Étapes.** Session liée à un hôte ; cookies en mémoire ; `form(page)` puis `submit(form, changes)`, sans `post_form` (D9, forme confirmée avec `veilleur-marches` avant le lot) ;
  refus des champs `password` ; fermeture par la portée de collecte ; guide d'écriture d'un collecteur ; surface.
- **Critères d'acceptation.**
  1. DV-02, critères 1 à 7 (SPEC §11).
  2. Un cookie `Domain=example.org` reçu de `www.example.org` n'est pas envoyé à `data.example.org`.
  3. Un cookie `Secure` n'est pas envoyé en `http`.
  4. La 101ᵉ requête d'une session échoue avec `session_quota_exceeded`.
  5. Aucun fichier n'est créé dans le dossier d'état pendant une collecte en session (comparaison avant et après).
- **Références.** ADR-0024, ADR-0023, ADR-0028 ; SPEC DV-02, §3.
- **Risques.** Le plus gros ajout ; dépend de l'analyseur HTML de `page` (R17).
- **Effort.** L
- **Statut.** à faire

### J12-L2 — Expiration des éléments (DV-06)

- **Objectif.** Ajouter `CollectedItem.expires_at`.
- **Critères d'acceptation.**
  1. DV-06, critères 1 à 4 (SPEC §11).
  2. Un `expires_at` sans fuseau est ignoré et l'état de la collecte porte `bad_expiry`.
  3. Une base 0.2.0 est migrée avec sauvegarde.
- **Références.** ADR-0027, ADR-0011 ; SPEC DV-06, EF-31.
- **Risques.** Interaction avec `reported` et les `state` déjà livrés (ADR-0011).
- **Effort.** M
- **Statut.** à faire

### J12-L3 — Publication 0.3.0

- **Objectif.** Préparer la version 0.3.0, comme J10-L3.
- **Critères d'acceptation.** Ceux de J10-L3, avec 0.3.0 et sans le critère 2.
- **Références.** ADR-0021, ADR-0028.
- **Risques.** Faible.
- **Effort.** S
- **Statut.** à faire

## J13 — Exactitude (réserves P3, COULD)

### J13-L1 — Export et rotations

- **Objectif.** Lever R15 autant que possible.
- **Critères d'acceptation.**
  1. Les quatre `xfail` de R15 hors « accepted limit » passent sans marqueur.
  2. Les deux cas « accepted limit » passent, ou restent `xfail` avec une décision de l'utilisateur inscrite dans
     l'ADR-0019 (piste : ouvrir les paquets conservés pour adopter leurs déclarations avant d'accepter le `state`).
- **Références.** R15 ; ADR-0019 ; SPEC ES-05, EF-45, EF-51 ; protocole §6.3.
- **Risques.** Le plus difficile des lots de réserves (3 passages du vérificateur en G4).
- **Effort.** L
- **Statut.** à faire

### J13-L2 — Abonnements et paramètres

- **Objectif.** Lever R16 et R17.
- **Critères d'acceptation.**
  1. Les quatre `xfail` de R16 et R17 passent sans marqueur.
  2. Le schéma du paramètre `pattern` du filtre `regex` décrit la syntaxe RE2 dans sa description.
- **Références.** R16, R17 ; SPEC EF-02, EF-10, EF-12.
- **Effort.** M
- **Statut.** à faire

### J13-L3 — Écarts divers du serveur

- **Objectif.** Lever R18.
- **Critères d'acceptation.**
  1. `tests/verif/test_g2_pass2.py::test_filter_returning_a_bad_address_is_counted_as_a_filter_failure` passe sans
     `xfail`.
  2. `1` et `1.0` dans les paramètres donnent la même collecte ; `subscription show` et `export` refusent un `uid`
     ambigu entre jumelages en demandant le jumelage ; un `GET` avec corps reçoit `400` ; `export` après purge
     n'écrit pas de paquet redondant ; `cut` lit `connection.sock` une seule fois.
- **Références.** R18 ; SPEC EF-04, §7.4.
- **Effort.** M
- **Statut.** à faire

### J13-L4 — Rendus

- **Objectif.** Lever R19.
- **Critères d'acceptation.** Les quatre `xfail` de R19 passent sans marqueur.
- **Références.** R19 ; ADR-0018 ; SPEC EF-43.
- **Effort.** S
- **Statut.** à faire

### J13-L5 — Déploiement

- **Objectif.** Lever R20.
- **Critères d'acceptation.**
  1. Les dix `xfail` de R20 passent sans marqueur, ou ceux « outside the specification » sont gardés par décision
     inscrite dans l'ADR-0020.
  2. Le bloc de frontal nginx proposé pour ntfy contient `proxy_buffering off` et la mise à niveau WebSocket.
- **Références.** R20 ; ADR-0020 ; SPEC ENF-01, ENF-03, ENF-03b.
- **Effort.** M
- **Statut.** à faire

## J14 — Confort et entretien (réserves P4, COULD)

### J14-L1 — Aide française et recherche de secrets

- **Objectif.** Lever R21 et le second point de R22.
- **Critères d'acceptation.**
  1. `tests/verif/test_g2_cli.py::test_french_help_has_no_english_placeholder` passe sans `xfail`.
  2. `gitleaks dir <chemin absolu du dépôt>` ne rend aucune alerte.
- **Références.** R21, R22 ; ADR-0005, ADR-0021.
- **Effort.** S
- **Statut.** à faire

### J14-L2 — Actions de la CI (Dependabot #8, #9)

- **Objectif.** Lever R25.
- **Critères d'acceptation.**
  1. `actions/checkout` et `astral-sh/setup-uv` sont aux versions proposées (ou plus récentes), fixées par empreinte
     avec leur numéro en commentaire ; `tests/test_repository.py` et `tests/verif/test_g6_release.py` passent.
  2. La CI de la PR est verte sur tous les travaux ; les PR #8 et #9 sont closes par l'utilisateur.
- **Références.** R25 ; ADR-0021.
- **Risques.** Sauts de version majeure : options renommées (`setup-uv`).
- **Effort.** S
- **Statut.** à faire

### J14-L3 — Charge (ENF-07)

- **Objectif.** Vérifier ENF-07 (premier point de R23).
- **Critères d'acceptation.**
  1. Un test marqué `slow` crée 300 abonnements sur un collecteur factice, lance un tour complet en moins de 60 s et
     la mémoire maximale du processus reste sous 1 Go (`resource.getrusage`).
  2. `just test` ne lance pas les tests `slow` ; `just slow` les lance.
- **Références.** R23 ; SPEC ENF-07.
- **Effort.** S
- **Statut.** à faire

## Réserves

Classées de la plus à la moins importante : sécurité et secrets, puis disponibilité du tour, puis exactitude, puis
confort. Les tests cités sont dans `tests/verif/`. `/livrer` ajoute les réserves nouvelles à la suite.

| Id | Priorité | Origine | Réserve | Test `xfail` | Levée par |
|---|---|---|---|---|---|
| R01 | P1 | G1 (PR #2), G2 (PR #3), G4 (PR #5) | Correctifs jamais revus : 7ᵉ passage de G1 (`a48c755`, clés publiques d'ordre faible, diff depuis `383b9ca`) ; B2 de G2 (`0e30a66`, élément trop profond) ; inscription de la limite ES-05 et passage en `xfail` de ses cas (G4) | cas « accepted limit » de `test_g4_verif_pass3.py` | J8-L1 |
| R02 | P1 | G4 (PR #5) | Un paquet forgé couvert par un `state` valide est ignoré sans signalement | `test_g4_verif_pass3.py::test_a_forged_package_is_reported_even_when_a_state_covers_it` | J8-L2 |
| R03 | P1 | G4 (PR #5) | Un code de jumelage passé en argument est répété sur stderr | `test_g4_verif.py::test_a_code_given_as_an_argument_is_not_repeated` | J8-L2 |
| R04 | P1 | G2 (PR #3) | Requêtes non authentifiées non limitées en débit ; corps lu avant l'authentification | aucun | J8-L3 |
| R05 | P1 | G3 (PR #4) | ES-08 : une réponse `304` sert le cache sans contrôler son type | `test_g3_verif.py::test_a_cached_answer_is_checked_against_the_expected_content_types` | J8-L4 |
| R06 | P1 | G3 (PR #4) | Le webhook transmet le sujet ntfy du jumelage à un tiers | aucun | J8-L4 |
| R07 | P1 | G5 (PR #6) | L'unité qui tire les jetons ntfy tourne en root sans durcissement | `test_g5_verif.py::test_the_unit_that_draws_the_tokens_is_hardened` | J8-L4 |
| R08 | P1 | G2 (PR #3) | `veilleur.db` en 0644 ; atténué par le dossier d'état en 0700 et `UMask=0077` [Certain : code lu], d'où son rang | aucun | J8-L3 |
| R09 | P2 | G2 (PR #3) | EF-05 : un greffon qui viole son contrat (liste paresseuse qui lève, code non textuel) arrête le tour | `test_g2_core.py::test_lazy_collected_items_that_fail_do_not_stop_the_round`, `::test_collector_error_with_a_non_string_code_does_not_stop_the_round` | J11-L1 |
| R10 | P2 | G2 (PR #3) | Déclaration d'équipe cassée (greffon absent) : `round` et `serve` échouent au lieu de `collector_missing` | `test_g2_cli.py::test_a_broken_team_declaration_does_not_stop_the_other_subscriptions` | J11-L1 |
| R11 | P2 | G2 (PR #3) | Une faute dans `pairings` d'une déclaration d'équipe supprime l'abonnement | aucun | J11-L1 |
| R12 | P2 | G2 (PR #3) | ES-05 : le service ne suit pas un `key rotate` d'un autre processus ; deux rotations en moins de 90 jours : la seconde remplace la première déclaration | `test_g2_core.py::test_running_service_follows_a_key_rotation`, `::test_two_rotations_within_90_days_keep_receivers_following` | J11-L2 |
| R13 | P2 | G2, G3, G4 (PR #3, #4, #5) | Coûts non bornés : motifs RE2 jusqu'à ≈ 4 s par champ ; cache des motifs sans borne ; `history` sans plafond de tâches ; réponse JSON très profonde (`RecursionError`) ; lecture du corps jusqu'à ≈ 2× le délai | `test_g3_pass3.py::test_the_compiled_pattern_cache_is_bounded`, `test_g4_verif.py::test_a_very_deep_answer_is_a_refusal` | J11-L3 |
| R14 | P2 | G4 (PR #5) | Récepteur : code de jumelage non UTF-8 → trace d'appels (traité avec R03, même code) | `test_g4_verif.py::test_a_pairing_code_that_is_not_text_is_refused_cleanly` | J8-L2 |
| R15 | P3 | G4 (PR #5) | Export et rotations : pas de `state` entre la fin des 90 jours et le tour suivant ; paquet jugé sur sa date et non sa clé ; deux rotations sans paquet intermédiaire ; `state` reconstruit avant un `delta` lisible de même numéro ; limite admise (trou purgé et deux rotations ; piste : ouvrir les paquets conservés pour adopter leurs déclarations) | `test_g4_verif_pass3.py::test_a_member_back_after_a_purge_follows_two_rotations_from_a_folder`, `::test_a_member_back_after_a_purge_follows_two_rotations_over_http`, `::test_two_rotations_without_a_package_between_them_are_followed`, `::test_a_member_able_to_read_the_last_delta_still_gets_it`, `::test_an_export_just_after_the_window_with_packages_not_yet_purged` ; `test_g4_verif_pass2.py::test_a_package_signed_by_the_old_key_just_after_the_rotation_is_replaced_too` | J13-L1 |
| R16 | P3 | G2 (PR #3) | EF-10 : `sync_team` duplique un abonnement supprimé puis redéclaré dans la même seconde | `test_g2_core.py::test_team_subscription_removed_then_declared_again_exists_once` | J13-L2 |
| R17 | P3 | G2, G3 (PR #3, #4) | EF-12 : surrogate isolé → 500 ; sélecteur de `page` non contrôlé à la réception ; virgule entre guillemets dans un sélecteur ; schéma de `pattern` muet sur RE2 | `test_g2_api.py::test_lone_surrogate_in_parameters_is_a_400` ; `test_g3_verif.py::test_unsupported_page_selector_is_refused_on_reception`, `::test_quoted_attribute_value_with_a_comma` | J13-L2 |
| R18 | P3 | G2, G3 (PR #3, #4) | Filtre qui renvoie une adresse invalide compté `package_too_large` ; `1` et `1.0` : deux collectes (EF-04) ; `subscription show`/`export` par `uid` ambigus ; `export` après purge redondant ; `GET` avec corps accepté ; course rare dans `cut` (`transport.py`) | `test_g2_pass2.py::test_filter_returning_a_bad_address_is_counted_as_a_filter_failure` | J13-L3 |
| R19 | P3 | G4 (PR #5) | Rendus : U+061C non retiré ; adresses hors du plafond de 2 millions de caractères ; texte de lien non abrégé | `test_g4_verif.py::test_the_arabic_letter_mark_is_removed`, `::test_addresses_count_against_the_cap_of_a_rendering`, `::test_the_text_of_a_link_is_shortened` ; `test_g4_verif_pass2.py::test_an_address_with_the_arabic_letter_mark_is_not_a_link` | J13-L4 |
| R20 | P3 | G5 (PR #6) | Déploiement : port 2019 accepté ; `ntfy.listenAddress` IPv6 sans crochets ; autres écritures de l'adresse joker ; formes inutilisables de `publicHost` ; `builtins.getFlake` sans `rev` dans le guide ; unité socket, `defaultSSLListenPort` et `listenAddresses` de sshd non lus ; faux positif sshd ; `backupPaths` non vide module désactivé ; bloc de frontal ntfy (`proxy_buffering`, WebSocket) | `test_g5_pass3.py::test_the_internal_port_is_not_the_admin_port_of_caddy`, `::test_the_tls_default_port_of_nginx_is_reported`, `::test_a_port_given_in_the_listen_addresses_of_sshd_is_reported`, `::test_sshd_bound_to_another_address_is_accepted` ; `test_g5_pass2.py::test_an_ipv6_address_for_ntfy_is_refused_or_bracketed`, `::test_a_socket_unit_is_reported` ; `test_g5_verif.py::test_other_spellings_of_the_wildcard_are_refused`, `::test_a_public_host_that_is_not_a_host_is_refused`, `::test_the_documented_get_flake_reference_is_locked`, `::test_a_disabled_service_lists_nothing_to_back_up` | J13-L5 |
| R21 | P4 | G2 (PR #3) | Aide française : `LABEL`, `LIMIT`, `AFTER`, `LISTEN`, `PORT` non traduits ; argument `collecteur` sans aide | `test_g2_cli.py::test_french_help_has_no_english_placeholder` | J14-L1 |
| R22 | P4 | G6 (PR #7) | `CONTRIBUTING*.md` ne citent pas `tools/check_vectors.py` ; exclusion `.gitleaks.toml` dépendante du dossier de lancement | `test_g6_release.py::test_the_guide_lists_every_check_of_the_ci` | J7-L1 (premier point), J14-L1 (second) |
| R23 | P4 | G5 (PR #6) | Non vérifié : charge ENF-07, certificat Let's Encrypt réel, `aarch64-linux` | aucun | J14-L3 (charge) ; Let's Encrypt et `aarch64-linux` : vérification de l'utilisateur sur une machine réelle |
| R24 | P4 | G6 (PR #7) | Marque : recherche limitée à l'INPI (TMview, WIPO non consultés) | aucun | action de l'utilisateur, pas un lot |
| R25 | P4 | entretien | PR Dependabot #8 (`actions/checkout` 4 → 7) et #9 (`setup-uv` 6 → 10), sauts majeurs | aucun | J14-L2 |
| R26 | — | G3 (PR #4) | Quota de 200 requêtes par hôte jamais remis à zéro dans `serve` (fusionnée avec DV-03) | aucun | J10-L2 |
| R27 | P4 | J7-L1 | `tools/ci_load.py` : l'alerte « plus de 20 minutes » ne nomme pas le travail en cause (ADR-0029) | `test_j7_l1_standard.py::test_a_workflow_above_20_minutes_names_the_job_in_cause` | à planifier (J14) |
| R28 | P4 | J7-L1 | `tools/ci_load.py` ne mesure que les exécutions réussies : une CI qui dépasse `timeout-minutes` n'est jamais comptée | `test_j7_l1_standard.py::test_runs_that_timed_out_still_count` | à planifier (J14) |
| R29 | P4 | J7-L1 | Non vérifié : flux `CI load` sur GitHub (`actions/checkout` avec seulement `actions: read`, médiane réelle du travail Nix sous 20 min) ; GitHub désactive un flux `schedule` après 60 jours sans activité | aucun | vérification de l'utilisateur (premier `workflow_dispatch`) |
| R31 | P4 | J7-L1 (PR #13) | Seuil D16 « deux fois la matrice » probablement dépassé : sur la PR #13, `just test (nix develop)` dure 5 min 35 s contre 1 min 26 s pour la matrice la plus lente (≈ 3,9 fois) ; le flux `CI load` échouerait chaque semaine | aucun | à planifier (J14) : revoir le seuil de D16 ou la mesure |
| R30 | P4 | J7-L1 | `LD_LIBRARY_PATH` (libstdc++) posé sur tout le shell de développement ; `xfail_tests` ne voit ni `pytestmark`, ni `pytest.param(marks=…)`, ni `pytest.xfail()` | aucun | à planifier (J14) |
| R32 | P4 | J7-L2 (PR #14) | L'assertion de `test_j7_l1_standard.py` remplacée par D17 ne lit que les chemins `.md` entre accents graves du premier paragraphe « Documents qui font foi » : une mention sans accents graves de l'ancien cahier passerait | aucun | à planifier (J14) |
| R33 | P4 | J7-L2 (PR #14) | `deploy/nixos/module.nix` : les deux messages d'assertion `listenAddress` lus par l'administrateur changent de libellé (« spec ES-09 ») ; aucun test ne les lit | aucun | à planifier (J13-L5) |
| R34 | P4 | J7-L2 (PR #14) | Les tests comparés à `main` ou à `c576de4` sont ignorés sur un clone superficiel (CI, `actions/checkout` sans `fetch-depth`) : constantes figées de D17 et critère 3 non rejoués en CI | aucun | à planifier (J14) |
| R35 | P4 | J7-L3 (PR #15) | Écart au critère 3 de J7-L3 admis par D18 : `tests/verif/test_j7_l2_pointers.py` modifié (comparaison fixée sur `c576de4...c307a5c`, commit `35c517d`) | `test_j7_l3_surface.py::test_the_lot_only_adds_test_files` | aucun lot : écart admis (D18) |
| R36 | P4 | J7-L3 (PR #15) | Les *entry points* des filtres et rendus pointent vers les sous-modules et non vers le réexport de `__init__` que prévoit l'ADR-0029 (même classe chargée) ; affaiblit à terme la garantie de réexport de l'ADR-0028 | `test_j7_l3_surface.py::test_the_entry_points_still_name_the_package_modules` | à planifier (J14) |
| R37 | P4 | J7-L3 (PR #15) | Hors spécification : `tests/test_plugin_api.py` ne fige pas `@runtime_checkable` sur `ParamsCheck` et `SetFilter`, dont le serveur se sert par `isinstance` | aucun | à planifier (J14) |
| R38 | P4 | J7-L3 (PR #15) | Hors spécification : le `__module__` des classes déplacées change (`veilleur.adapters.filters` → `veilleur.adapters.filters.keywords`, etc.) ; à citer dans les notes de version | aucun | prochaine publication |
