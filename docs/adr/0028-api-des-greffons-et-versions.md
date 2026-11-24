# ADR-0028 — Surface publique de l'API des greffons, compatibilité et versions

- **Statut :** Accepté
- **Date :** 2026-11-19 ; accepté le 2026-11-24 (D7)
- **Exigences :** EF-01, EF-20, EF-43, EF-52 ; brief §2.3

## Contexte

Le greffon `veilleur-marches` dépend de `veilleur.collectors`, des ports, de `Collected`, `CollectedItem` et du
client HTTP. Rien ne dit quels modules sont publics. La reprise réorganise le code (ADR-0029) et les demandes DV
étendent l'API. Les greffons s'ajoutent à l'environnement Nix par le chemin de recherche Python (ADR-0020) : aucun
résolveur ne vérifie leur dépendance déclarée envers Veilleur.

## Options considérées

1. Statu quo, surface implicite : une réorganisation peut casser un greffon sans que rien ne le signale.
2. **Déclarer la surface actuelle publique et la figer par un test**, sans changer les chemins d'import.
3. Façade nouvelle (`veilleur.plugin`) qui réexporte tout : deux chemins à maintenir, et les greffons existants
   importent déjà les chemins actuels. Possible plus tard.

## Décision

Option 2.

- **Surface publique, version 1** : groupes d'*entry points* `veilleur.collectors`, `veilleur.filters`,
  `veilleur.renderers`, `veilleur.notifiers` ; modules `veilleur.core.ports.plugins` (tous les noms publics),
  `veilleur.core.ports.http` (`HttpClient`, `HttpResponse`), `veilleur.core.domain.model` (`Collected`,
  `CollectedItem`, `ItemChange`, `SourceStatus`, `Kind`, `Change`), `veilleur.core.domain.errors`
  (`CollectorError`), `veilleur.core.domain.schema` (`validate`) ; `veilleur.__version__`.
- Un test (`tests/test_plugin_api.py`) fige noms, champs des objets de données (ordre et défauts) et méthodes des
  protocoles. Toute modification de ce test est une décision visible dans une PR.
- **Compatibilité** : en 0.x, une version mineure n'apporte que des ajouts (champ final avec défaut, méthode
  nouvelle). Un retrait ou un renommage garde un alias pendant au moins une version mineure, signalé par
  `DeprecationWarning` et les notes de version.
- **Réorganisation** : aucun module de la surface ne change de chemin ; les modules internes déplacés (`adapters`)
  gardent un réexport tant que les *entry points* fournis y renvoient.
- **Versions** : 0.2.0 après la politique `robots.txt`, DV-04, DV-05, DV-01 et DV-03 (jalons J9 et J10) ; 0.3.0 après
  DV-02 et DV-06 (J12). Un greffon vérifie `veilleur.__version__` au chargement s'il utilise un ajout.

## Conséquences

- Le greffon `veilleur-marches` peut se fier à la surface listée ; ses tests factices du client HTTP devront ajouter
  `post_json` et `session` le jour où il les utilise.
- `docs/{en,fr}/writing-a-collector.md` publie la liste.

## Sources

- `src/veilleur/core/ports/`, `examples/veilleur-example-collector/`, `deploy/nixos/tests/plugin/`, commit `0be164e`.
