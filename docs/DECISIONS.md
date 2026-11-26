# Veilleur — décisions à trancher

> Questions ouvertes de la reprise. Répondre sous chaque **Réponse**, puis passer les ADR concernés en `Accepté` ou
> `Rejeté`. Les ADR 0001 à 0021 (rétrospectifs) sont déjà `Accepté`.
>
> **État au 2026-11-24** : D1 à D16 répondues ; ADR 0022 à 0029 `Accepté`. Aucune décision ouverte.

## D1. Accepter le changement de politique `robots.txt` (passer outre avec alerte par défaut) ?
- Contexte : seul engagement public que la reprise change (README, guides, cahier §10 du 2026-11-18). Arguments, pratique
  comparable et cadre juridique dans [ADR-0022](adr/0022-politique-robots-txt.md). Le contre-exemple d'Anthropic
  (`Claude-User` suit `robots.txt`) montre que la pratique n'est pas unanime.
- Options : (a) `warn` par défaut, `enforce` réglable par instance et par hôte ; (b) `enforce` par défaut, `warn`
  réglable ; (c) statu quo (refus strict, aucun réglage).
- Recommandation : (a). Veilleur lit des adresses choisies par un humain, comme un lecteur de flux ; le respect strict
  ne garantissait de toute façon pas le droit (une opposition peut être dans les CGU) ; l'alerte rend le choix
  visible. Si l'image publique compte plus que l'usage, (b) coûte une ligne.
- **Réponse :** (a)

## D2. Numéroter les nouveaux jalons à partir de J7 ?
- Contexte : le brief le suppose, pour ne pas confondre avec G0 à G6 ([PLAN](PLAN.md), « Historique »).
- Options : (a) J7 et suivants ; (b) J1 et suivants (collision de lecture avec G1…) ; (c) J0-L1 réservé, puis J1.
- Recommandation : (a), la continuité de numéro se lit sans table.
- **Réponse :** (a)

## D3. Garder la matrice uv de la CI à côté du nouveau travail `nix develop -c just test` ?
- Contexte : le standard demande `nix develop -c just test` ; `nix develop` ne fournit que Python 3.12, et les
  contrôles requis de `main` portent le nom des travaux de la matrice ([ADR-0029](adr/0029-mise-au-standard-et-organisation-du-code.md)).
- Options : (a) ajouter le travail `just test` et garder la matrice ; (b) remplacer la matrice (perte de 3.13, contrôles
  requis à changer par l'utilisateur dans les réglages de `main`) ; (c) faire de `just test` la commande de la matrice.
- Recommandation : (a) ; (b) plus tard, si la double CI coûte trop.
- **Réponse :** (a), avec un script pour surveiller la charge et alerter au besoin

## D4. Omettre `env-up` et `env-down` du `justfile` ?
- Contexte : le standard les définit par `docker compose` ; Veilleur n'a pas de fichier compose, ses essais de service
  se font en VM (`nix flake check`) ([ADR-0029](adr/0029-mise-au-standard-et-organisation-du-code.md)).
- Options : (a) les omettre et fournir `just vm` ; (b) écrire un `compose.yaml` minimal (service + Caddy) pour `bac up` ;
  (c) recettes vides qui expliquent l'absence.
- Recommandation : (a) ; un compose ferait un second chemin de déploiement à maintenir.
- **Réponse :** (a)

## D5. Découper les greffons fournis en un module chacun (`filters`, `renderers`, `notifiers`) ?
- Contexte : ils sont écrits dans des `__init__.py` ; rien ne casse, seule la cohérence avec `adapters/collectors` le
  justifie ([ADR-0029](adr/0029-mise-au-standard-et-organisation-du-code.md), lot J7-L3).
- Options : (a) découper, avec réexport ; (b) ne pas découper.
- Recommandation : (b), sauf envie de cohérence : la règle de la reprise est de ne réorganiser que ce qu'un besoin
  justifie. Le test de surface de l'API (J7-L3) se fait dans les deux cas.
- **Réponse :** (a)

## D6. Étiquettes : lesquelles, et qui les pose ?
- Contexte : le `CLAUDE.md` du projet dit « étiquette par lot fusionné (`g0`, `g1`…), puis versions », posées par
  Claude ; la règle commune interdit toute écriture publique sans demande explicite. Avec 27 lots, une étiquette par
  lot devient du bruit.
- Options : (a) une étiquette par jalon (`j7`…) et par version (`v0.2.0`), posée par l'utilisateur ; (b) même chose,
  posée par Claude sur demande explicite au moment voulu ; (c) versions seulement.
- Recommandation : (c) versions seulement, posées par l'utilisateur ou par Claude sur demande ; les jalons se lisent
  dans `docs/PLAN.md` et les PR.
- **Réponse :** (c)

## D7. Ordre des jalons : sécurité, puis `robots.txt` et 0.2.0, puis disponibilité, puis DV-02 ?
- Contexte : [PLAN](PLAN.md) suit la recommandation du brief : P1 avant DV-01 ; politique `robots.txt` avant DV-01 et
  DV-02 ; DV-03 avec la réserve du quota ; DV-05 avant l'alerte ; P2 avant DV-02. Ajouts : DV-04 avec l'analyseur
  (J9-L1) ; R14 traitée avec R03 (même code) ; R08 gardée en P1 mais dernière (atténuée deux fois).
- Options : (a) l'ordre du plan ; (b) DV-01 avant J8, si le greffon en a un besoin urgent (J8 coûte 4 lots) ;
  (c) autre ordre.
- Recommandation : (a). Versions : 0.2.0 à la fin de J10, 0.3.0 à la fin de J12.
- **Réponse :** (a)

## D8. Protego en dépendance de développement, comme oracle des tests de l'analyseur `robots.txt` ?
- Contexte : l'analyseur propre est nécessaire pour nommer la règle en cause ; Protego (BSD-3, sans dépendance) suit
  RFC 9309 ([SPEC §12](SPEC.md), [ADR-0022](adr/0022-politique-robots-txt.md)). Précédent : PyNaCl (ADR-0009).
- Options : (a) oui, en développement seulement ; (b) non, exemples de la RFC seulement ; (c) Protego en exécution pour
  la décision, analyseur propre pour nommer la règle.
- Recommandation : (a).
- **Réponse :** (a)

## D9. Forme des sessions (DV-02) : formulaire lu dans une page, ou `post_form(url, fields)` libre ?
- Contexte : DV-02 demande `session.post_form(url, fields)` et le refus des formulaires à champ `password` ; avec des
  champs libres, le client ne voit pas le formulaire et ne peut pas vérifier ce refus
  ([ADR-0024](adr/0024-sessions-ephemeres.md)).
- Options : (a) `session.form(page)` puis `session.submit(form, changes)` seulement ; (b) les deux, `post_form` sans
  contrôle de mot de passe ; (c) `post_form` seul, en refusant les noms de champ qui ressemblent à un mot de passe.
- Recommandation : (a) ; à confirmer avec le greffon `veilleur-marches`, dont la demande change de forme.
- **Réponse :** (a)

## D10. Mettre les avertissements (DV-05) dans le manifeste des paquets ?
- Contexte : le protocole 1.0 impose d'ignorer les membres inconnus de `sources` : un membre `warnings` serait une
  version 1.1 (spécification, traduction, vecteurs) ([ADR-0027](adr/0027-avertissements-et-expiration.md)).
- Options : (a) non en 0.2.0 : état des sources côté serveur et `veilleur sources` seulement ; (b) oui, protocole 1.1.
- Recommandation : (a) ; DV-05 vise la visibilité pour l'administrateur ; (b) reste possible sans rupture.
- **Réponse :** (a)

## D11. Corps du webhook (R06) : remplacer `topic` par `pairing` (`key_id`) ?
- Contexte : le corps transmet le sujet ntfy du jumelage au tiers qui reçoit le webhook ; un récepteur de webhook doit
  pourtant savoir de quel jumelage il s'agit (lot J8-L4).
- Options : (a) `pairing` = `key_id` (identifiant qui circule déjà en clair dans `Authorization`) ; (b) HMAC du sujet
  avec la clé du webhook ; (c) retirer l'identifiant.
- Recommandation : (a), annoncé dans les notes de version.
- **Réponse :** (a)

## D12. Valeurs supposées par les ADR et le plan
- Contexte : valeurs étiquetées [Suppose], qu'aucun document ne fixait.
- Options, à accepter en bloc ou à corriger une par une :
  - quota maximal par hôte 10 000, intervalle minimal 1 s (ADR-0025) ;
  - plafond de `Crawl-delay` 60 s (ADR-0026, DV-04) ;
  - `robots.txt` illisible relu après 1 h (ADR-0022) ;
  - 8 avertissements par collecte (ADR-0027) ;
  - session : 100 requêtes, 50 cookies de 4 Kio (ADR-0024) ;
  - 300 réponses `401` par minute avant `429` (J8-L3) ; 4 tâches `history` en attente par jumelage (J11-L3).
- Recommandation : accepter ; toutes se changent par une constante et un test.
- **Réponse :** accepter

## D13. Réalerter quand `robots.txt` change ?
- Contexte : le brief le suppose ; l'ADR-0022 garde l'empreinte de `robots.txt` avec chaque alerte.
- Options : (a) réalerter si l'empreinte change et que l'adresse est encore interdite ; (b) une seule alerte par couple
  (collecte, hôte), pour toujours ; (c) réalerter aussi périodiquement (par exemple tous les 90 jours).
- Recommandation : (a) ; un site qui modifie ses règles mérite un nouveau regard de l'administrateur.
- **Réponse :** (a)

## D14. Ajouter `Retry-After` à EF-06 ?
- Contexte : le brief compte `Retry-After` dans « ce qui reste dû » ; la reprise constate que le client ne le lit pas
  (`docs/REPRISE.md`, E4). C'est donc une exigence nouvelle ([ADR-0026](adr/0026-crawl-delay-et-retry-after.md),
  lot J9-L1).
- Options : (a) oui, sur `429` et `503`, plafonné à la fin du tour ; (b) non, hors de la reprise.
- Recommandation : (a) ; même code que `Crawl-delay`, coût faible.
- **Réponse :** (a)

## D15. Garder `cahier_des_charges.MD` et `plan.md` comme renvois, ou les supprimer ?
- Contexte : le brief demande un renvoi (lot J7-L2) ; l'historique git les garde de toute façon.
- Options : (a) renvoi de quelques lignes ; (b) suppression.
- Recommandation : (a) jusqu'à 0.2.0 (des liens externes peuvent y pointer), puis (b).
- **Réponse :** (a)

## D16. Seuils et canal de la surveillance de charge de la CI (suite de D3)
- Contexte : la réponse à D3 demande « un script pour surveiller la charge et alerter au besoin ». Interprété ainsi
  [Suppose] : la charge est la durée des exécutions de CI sur les exécuteurs GitHub (`ubuntu-latest`, aucun exécuteur
  sur NixKS) ; voir [ADR-0029](adr/0029-mise-au-standard-et-organisation-du-code.md) et le lot J7-L1.
- Options : (a) seuils 20 minutes pour le flux et deux fois la matrice pour `just test`, alerte par l'échec d'un flux
  planifié hebdomadaire (courriel de GitHub) ; (b) mêmes seuils, alerte ntfy depuis NixKS par une minuterie
  utilisateur (secret ntfy hors dépôt ; ntfy peu fiable sur le téléphone en 5G) ; (c) autre sens de « charge »
  (par exemple la charge de NixKS pendant `nix flake check` en local) : à préciser.
- Recommandation : (a) ; aucun secret, rien à installer, et rien ne s'écrit publiquement.
- **Réponse :** (a)

## D17. Tests de J7-L1 qui lisent les anciens documents (lot J7-L2)
- Contexte : une fois `plan.md` et `cahier_des_charges.MD` réduits à un renvoi, deux tests du vérificateur de J7-L1,
  non prévus par le plan, échouent : `tests/verif/test_j7_l1_standard.py::test_claude_md_keeps_the_token_table_of_the_former_plan`
  (tableau des droits du jeton de l'ancien `plan.md`) et `::test_every_identifier_of_the_former_specification_is_in_the_correspondence_table`
  (identifiants `EF`/`ES`/`ENF` de l'ancien cahier). Les corriger sort du critère 3 de J7-L2.
- Options : (a) figer l'ancien contenu (commit `c576de4`) en constantes dans le test ; (b) le lire par `git show`
  (historique complet requis dans la CI) ; (c) rediriger vers `docs/REPRISE.md` (test presque tautologique) ;
  (d) arrêt du lot.
- Recommandation : (a) ; la vérification ne perd rien.
- **Réponse :** (a), le 2026-11-24. Écart au critère 3 de J7-L2 admis pour ces deux tests, pour l'assertion du même
  fichier qui nommait l'ancien cahier (critère 4, remplacée par « tout `.md` cité dans le paragraphe qui fait foi est
  sous `docs/` ») et pour trois raisons de `xfail` qui citaient « cahier » (`test_g4_verif_pass3.py`,
  `test_g5_pass2.py`).

## D18. Test de J7-L2 qui compare à `main` (lot J7-L3)
- Contexte : `tests/verif/test_j7_l2_pointers.py::test_tests_changed_only_in_docstrings_comments_and_the_redirected_paths`
  comparait `main...HEAD` et l'arbre de travail. Une fois J7-L2 fusionné, il visait le diff du lot suivant : J7-L3, qui
  ajoute `tests/test_plugin_api.py` (critère 1), le faisait échouer, donc `just test` (critère 4). Les critères 3 et 4
  de J7-L3 étaient incompatibles tels quels ; le corriger sort du critère 3.
- Options : (a) fixer la comparaison sur les commits de J7-L2 (`c576de4...c307a5c`, état final lu dans `c307a5c`),
  assertion inchangée ; (b) arrêt du lot.
- **Réponse :** (a), le 2026-11-24 (commit `35c517d`). Écart au critère 3 de J7-L3 admis pour ce seul fichier.
