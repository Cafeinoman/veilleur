# ADR-0029 — Mise au standard du dépôt et organisation du code

- **Statut :** Accepté
- **Date :** 2026-11-19 ; accepté le 2026-11-24 (D2, D3, D4, D5, D6, D15)
- **Exigences :** §7.1, §9 ; brief §4.1

## Contexte

Le dépôt a été construit avant le standard `/architecte` : pilotage dans `cahier_des_charges.MD` et `plan.md`, pas de
`justfile`, CI sans `nix develop`. L'inventaire du code contre §7.1 (`docs/REPRISE.md`, §3) relève peu d'écarts.

## Options considérées

- Réorganiser largement (un module par greffon, `tests/verif/` par exigence, réglages HTTP déplacés) ; **ne réorganiser
  que ce qu'un besoin justifie**, sans changement de comportement.
- CI : remplacer la matrice uv (Python 3.12 et 3.13) par `nix develop -c just test` (Python 3.12 seul, et noms des
  contrôles requis de `main` à changer) ; **ajouter un travail `just test`** et garder la matrice.

## Décision

- **Pilotage** : `docs/SPEC.md`, `docs/adr/`, `docs/PLAN.md` font foi ; `cahier_des_charges.MD` et `plan.md` sont
  remplacés par un renvoi après la fusion de la PR `claude/architecture` (lot J7-L2) ; les deux tests qui les lisent
  (`tests/verif/test_design_follows_spec.py`, `tests/verif/test_g6_release.py::test_the_specification_records_the_decisions_of_the_release`)
  sont redirigés vers `docs/SPEC.md` et l'ADR-0021, avec des assertions équivalentes.
- **Outillage** : `justfile` avec `test` (pytest, ruff, mypy, lint-imports, `tools/check_vectors.py`,
  `tools/protocol_vectors.py --check`), `fmt` (`ruff format` et `ruff check --fix`), `vm` (`nix flake check -L`) ;
  pas d'`env-up`/`env-down` (aucun service Docker : les essais de service se font en VM) [D4] ; `just` dans
  `devShells.default` ; nouveau travail de CI `nix develop -c just test`, matrice uv gardée [D3].
- **Surveillance de la charge de la CI** [D3] : script `tools/ci_load.py` (sans dépendance, appelle `gh run list`
  et `gh run view --json jobs`) qui mesure, sur les 20 dernières exécutions du flux de CI sur `main`, la durée
  médiane de chaque travail et du flux entier ; il sort avec un code non nul et un message nommant le travail en
  cause si le flux dépasse 20 minutes ou si le travail `just test` dure plus de deux fois le plus long travail de
  la matrice (D16). Recette `just ci-load`. Alerte : flux GitHub planifié chaque semaine (`schedule`)
  qui lance le script ; son échec est notifié par GitHub au propriétaire du dépôt [Probable], sans secret ni
  écriture publique. Une alerte qui se répète déclenche la question de l'option (b) de D3 (remplacer la matrice).
- **`CLAUDE.md`** réécrit au format de `/nouveau-projet` : documents qui font foi, commande `just test`, règle « un
  lot = un identifiant `J<n>-L<m>`, branche `claude/<identifiant>-<sujet>` », étiquettes de version seulement
  (`v0.2.0`…), posées par l'utilisateur ou par Claude sur demande explicite, plus d'étiquette par lot [D6], règles propres conservées (généricité,
  langues, licence, sécurité, tests sans réseau, droits du jeton GitHub repris de `plan.md` G0-R).
- **Code**, sans changement de comportement :
  - test de surface de l'API des greffons (ADR-0028) — justifié par les évolutions DV ;
  - références « cahier » des docstrings et en-têtes de tests remplacées par « spec » (identifiants inchangés) —
    justifié : le document cité disparaît ;
  - greffons fournis écrits dans des `__init__.py` (`adapters/filters`, `adapters/renderers`,
    `adapters/notifiers`) : découpés en un module par greffon, comme `adapters/collectors`, avec réexport depuis
    `__init__` pour les *entry points* [D5] — justifié par la cohérence avec `adapters/collectors` ; les chemins
    d'import et les classes chargées par les *entry points* ne changent pas (ADR-0028).
- **Non retenu** : renommer `tests/verif/` par exigence (ces fichiers sont la trace des passages ; leurs `xfail`
  renvoient à des réserves numérotées ; nouvelle convention pour les lots à venir : `tests/verif/test_<lot>_*.py`) ;
  déplacer les réglages HTTP de `apps/server/context.py` (le lot DV-03 les fait venir de la configuration, ce qui
  suffit).

## Conséquences

- Les lots J7 ne changent aucun comportement : les tests existants passent inchangés, sauf les deux redirigés.
- Les contrôles requis de `main` ne changent pas tant que l'utilisateur ne les modifie pas.

## Sources

- `~/.claude/skills/nouveau-projet/SKILL.md`, `~/.claude/skills/architecte/gabarit.md`, consultés le 2026-11-19 ;
  `.github/workflows/ci.yml`, `tests/verif/`, commit `0be164e`.
