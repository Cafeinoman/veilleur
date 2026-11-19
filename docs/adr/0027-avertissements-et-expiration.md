# ADR-0027 — Avertissements de collecte (DV-05), expiration des éléments (DV-06), portée de collecte

- **Statut :** Proposé
- **Date :** 2026-11-19
- **Exigences :** DV-05, DV-06, EF-07 (alerte `robots.txt`), EF-05, EF-31, EF-52

## Contexte

`Collected(complete=False)` ne dit pas pourquoi une collecte est partielle (DV-05). Une source lue par fenêtre
glissante reste partielle : ses éléments ne disparaissent jamais et le `state` grossit (DV-06). L'alerte
`robots.txt` (ADR-0022) a besoin du même canal que DV-05 : un code stable attaché à l'état d'une collecte, montré
par `veilleur sources`. Les deux doivent donc être livrés ensemble, DV-05 en premier.

## Options considérées

- Avertissements : texte libre (fuite de détails, intraduisible) ; **codes stables** `[a-z][a-z0-9_]{0,63}`.
- Où les montrer : table `source_status` et `veilleur sources` seulement ; **aussi dans le manifeste** (membre
  `warnings` de `sources`, que les lecteurs 1.0 doivent ignorer : protocole 1.1). Voir `docs/DECISIONS.md` (D10).
- Expiration : supprimer l'élément (perte de l'historique) ; **le marquer expiré**, le retirer de l'état courant et de
  `reported` sans publier `gone`.
- Avertissements du client HTTP vers le cœur : le client écrit en base (couplage entre adaptateurs) ; **portée de
  collecte** ouverte par le cœur sur un port serveur.

## Décision

- **DV-05.** `Collected` gagne `warnings: tuple[str, ...] = ()` (champ final, avec défaut : compatible). Au plus 8
  codes gardés par collecte [Suppose] ; un code invalide est écarté et remplacé par `bad_warning`, sans faire échouer
  la collecte. Les codes sont gardés dans `source_status` (migration) et affichés, traduits si connus, par
  `veilleur sources`. Ils ne figurent **pas** dans le manifeste en 0.2.0 (protocole inchangé) [Suppose, D10].
- **Portée de collecte.** Le cœur appelle le collecteur dans une portée ouverte par un port serveur
  (`ServerHttp.collection(collection_id)`, distinct du port `HttpClient` que voient les greffons) : à la sortie, même
  après une exception, le client rend ses avertissements (`robots_ignored` avec hôte et règle) et ferme les sessions
  de DV-02. Le cœur les ajoute à ceux du greffon, écrit l'événement et décide s'il y a alerte.
- **Notification.** `RoundCounts` gagne `robots_ignored: int = 0` (sources qui passent outre pour la première fois
  dans ce tour) ; `ntfy` l'écrit en clair, `webhook` ajoute le membre. Les avertissements de DV-05 ne sont pas comptés
  [Suppose].
- **DV-06.** `CollectedItem` gagne `expires_at: datetime | None = None`. Date avec fuseau, sinon ignorée et
  avertissement `bad_expiry`. Au tour où la date est passée, l'élément est marqué expiré : absent de l'état courant,
  du `state` et de `reported`, **jamais publié `gone`** ; revu après expiration, il redevient courant et paraît
  `new` dans le `delta` suivant. Aucun effet sur les paquets déjà scellés ni sur leur conservation.

## Conséquences

- Évolutions de l'API des greffons, toutes additives (ADR-0028) ; un greffon qui utilise `warnings` ou `expires_at`
  exige Veilleur ≥ 0.2.0 ou 0.3.0.
- Migrations `0003` (avertissements, alertes `robots.txt`) et `0004` (expiration).

## Sources

- `DEMANDES-VEILLEUR.md`, DV-05, DV-06 ; `src/veilleur/core/services/collect.py`, `core/domain/model.py` ;
  `docs/en/protocol.md` §7.5 (membres inconnus ignorés), commit `0be164e`.
