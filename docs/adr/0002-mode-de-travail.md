# ADR-0002 — Mode de travail : une branche et une PR par lot, un lot par session

- **Statut :** Accepté
- **Date :** 2026-11-15, révisée le 2026-11-19
- **Nature :** ADR rétrospective
- **Origine :** cahier §9, §10 (2026-11-15, 2ᵉ ligne ; 2026-11-19) ; `plan.md` « Mode de travail » ; PR #11

## Contexte

Le développement est entièrement assisté par Claude, sur un dépôt public dont `main` est protégée. Il fallait fixer
qui écrit, qui vérifie, qui fusionne, et quand Claude s'arrête.

## Options considérées

1. Envois directs sur `main` : écarté (dépôt public, aucune relecture).
2. Une branche et une PR par fonctionnalité, ouvertes par Claude, fusionnées par l'utilisateur, avec **enchaînement
   des lots sans confirmation** (décision du 2026-11-15).
3. Même règle, mais **un lot par session**, clos par `/clear` puis `/livrer` (vérificateur indépendant) : décision du
   2026-11-19, qui abandonne l'enchaînement.

## Décision

- Option 3. Une branche `claude/<lot>-<sujet>` par lot, créée depuis `main` à jour ; la PR est ouverte par `/livrer`
  après le passage du vérificateur ; la fusion est faite par l'utilisateur ; aucun envoi direct sur `main` après le
  premier commit ; `main` protégée (PR obligatoire, CI verte, administrateurs compris).
- Claude s'arrête sur une erreur qu'il ne sait pas résoudre ou un arbitrage impératif (choix qui modifie la
  spécification, contradiction entre documents, action irréversible hors du plan).
- L'enchaînement des lots sans confirmation est **abandonné** (2026-11-19).

## Conséquences

- Avec la reprise au standard, les lots prennent l'identifiant `J<n>-L<m>` de `docs/PLAN.md` et la branche
  `claude/<identifiant>-<sujet>` (ADR-0029). Les questions en attente passent de `plan.md` à `docs/DECISIONS.md`.
- Au plus deux passages du vérificateur par lot ; les écarts non bloquants deviennent des réserves de `PLAN.md`.

## Sources

- `cahier_des_charges.MD` §9, §10 ; `plan.md` « Mode de travail » ; `CLAUDE.md` du projet (commit `0be164e`).
- PR #11 « Drop the rule that chains batches without confirmation ».
