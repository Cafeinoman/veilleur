# Veilleur

*[English version](README.md)*

Veilleur est un **serveur de veille** auto-hébergé. Il collecte des informations depuis des sources branchables (flux RSS/Atom, API JSON, pages web, ou toute source écrite comme greffon), repère ce qui est nouveau ou a changé d'un tour à l'autre, en fait des **rapports** et les livre, **signés et chiffrés**, à des outils de réception. Ces outils sont hors du périmètre du projet ; un petit récepteur de référence montrera comment en écrire un.

> **État : début du développement.** Seul le squelette du projet existe ; rien n'est encore utilisable. La conception et la feuille de route sont dans [docs/fr/design.md](docs/fr/design.md).

## Principes

- **Un serveur par équipe, un administrateur.** Chaque membre jumelle une fois son outil de réception avec le serveur, en collant un code de jumelage.
- **Le serveur connaît ce qu'il collecte, jamais ce que les destinataires en font.**
- **Rapports signés et chiffrés**, livrés par HTTPS ou par simple transfert de fichiers, avec une notification facultative (ntfy, webhook) qui ne porte que des comptes.
- **Installation déclarative et durcie** sous NixOS (serveur dédié ou conteneur isolé), avec une solution de repli pour les autres distributions Linux.
- **Bilingue** : messages, rapports et documentation en français et en anglais.

## Développement

Il faut [uv](https://docs.astral.sh/uv/) et Python 3.12 ou plus récent.

```bash
uv sync
uv run pytest
uv run ruff check src tests
uv run mypy
uv run lint-imports
uv run veilleur --lang fr version
```

Traductions : voir [docs/fr/translating.md](docs/fr/translating.md).

## Licence

Veilleur est un logiciel libre sous [licence publique de l'Union européenne v. 1.2](LICENSE) (EUPL-1.2). L'EUPL est publiée dans toutes les langues officielles de l'Union européenne, toutes les versions faisant également foi.
