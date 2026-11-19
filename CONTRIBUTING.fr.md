# Contribuer à Veilleur

*[English version](CONTRIBUTING.md)*

Les failles se signalent en privé : voir [SECURITY.md](SECURITY.md).

## Périmètre

Veilleur est générique : une source propre à un domaine métier relève d'un greffon maintenu hors de ce dépôt. Voir [écrire un collecteur](docs/fr/writing-a-collector.md).

## Branches et *pull requests*

- Créez une branche par fonctionnalité, depuis `main` à jour.
- `main` est protégée : tout changement passe par une *pull request* dont la CI est verte.
- Écrivez des commits courts, à l'impératif et en anglais, qui expliquent pourquoi le changement est nécessaire.
- Décrivez dans la *pull request* ce qui change et ce que vous avez vérifié.
- En contribuant, vous acceptez que votre contribution soit publiée sous licence [EUPL-1.2](LICENSE).

## Contrôles

Ils doivent passer avant chaque commit :

```bash
uv sync --locked
uv run pytest
uv run ruff check src tests tools protocol receiver
uv run mypy
uv run lint-imports
```

Les tests n'utilisent jamais le réseau : servez-vous de réponses enregistrées et appelez directement l'application WSGI.

## Règles de code

- La première ligne de chaque fichier Python est `# SPDX-License-Identifier: EUPL-1.2`.
- Le code, les identifiants, les commentaires et les docstrings sont en anglais.
- `core` ne dépend ni du stockage, ni du réseau, ni de la traduction, ni de `adapters`, ni de `apps`.
- Les dépendances restent minimales et compatibles avec l'EUPL-1.2, et toute nouvelle dépendance se justifie. La cryptographie passe uniquement par `pycryptodomex`.
- Les journaux ne contiennent jamais de corps de requête, d'en-tête d'authentification, de secret, de paramètre d'abonnement ni d'adresse IP de membre.
- Les collecteurs n'accèdent au réseau que par le client HTTP du serveur.
- Une modification du protocole met à jour sa spécification normative, sa traduction et les vecteurs de test.
- Les exemples utilisent des domaines réservés (`example.org`, `example.net`) et aucune donnée personnelle.

## Traductions et documentation

- Tout texte lu par une personne passe par `_()` ou `ngettext()` de `veilleur.i18n`, avec un texte source en anglais et des paramètres nommés.
- Lancez ensuite `uv run python tools/i18n.py all` et traduisez les nouveaux messages dans le fichier `.po` français. Voir [traduire](docs/fr/translating.md).
- `docs/en/` et `docs/fr/` contiennent les mêmes fichiers : mettez à jour les deux.

## Recherche de secrets

L'environnement de développement Nix fournit `gitleaks`. Lancez `gitleaks git --redact .` avant de publier une branche.
