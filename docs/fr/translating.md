# Traduire Veilleur

*[English version](../en/translating.md)*

Veilleur parle anglais et français. Le code, les identifiants et les commentaires sont en anglais ; tout ce qu'une personne lit (ligne de commande, journaux, messages d'erreur de l'API, rapports, documentation) existe dans les deux langues.

## Messages

- Dans le code, entourer le texte destiné aux personnes de `_()` (de `veilleur.i18n`), en anglais : `_("show the version")`. Utiliser des paramètres nommés avec `str.format` : `_("Veilleur {version}").format(version=...)`, jamais de concaténation, pour que la traduction puisse déplacer les mots.
- Pour un texte qui dépend d'un nombre, utiliser `ngettext(singulier, pluriel, n)`.
- Le cœur (`veilleur.core`) ne traduit rien : il renvoie des codes stables, que les applications transforment en messages. `lint-imports` le vérifie.
- Les erreurs de l'API portent un `code` anglais stable, jamais traduit, et un `message` traduit.

Puis, depuis la racine du dépôt :

```bash
uv run python tools/i18n.py all
```

La commande extrait les textes dans `src/veilleur/locale/veilleur.pot`, les reporte dans `src/veilleur/locale/fr/LC_MESSAGES/veilleur.po` et compile `veilleur.mo`. Traduire les nouvelles entrées du `.po` (`msgstr` vide), puis lancer `uv run python tools/i18n.py compile`. Les fichiers `.po` et `.mo` sont tous deux suivis par git. Le récepteur de référence a son propre catalogue, traité par la même commande, dans `receiver/src/veilleur_receive/locale/` : il ne dépend pas du serveur.

Les tests échouent si un message n'a pas de traduction française, si une traduction est approximative (*fuzzy*) ou obsolète, si un paramètre a disparu, ou si le `.mo` n'est pas à jour.

## Choix de la langue

Par ordre de priorité : l'option `--lang` (ou, pour un rapport, la langue de l'abonnement), la variable d'environnement `VEILLEUR_LANG`, la langue du système (`LANGUAGE`, `LC_ALL`, `LC_MESSAGES`, `LANG`). À défaut : l'anglais.

La ligne de commande traduit aussi les textes standard d'`argparse` (utilisation, titres, erreurs) : voir `src/veilleur/apps/server/argparse_i18n.py`.

## Conventions du français

Une espace avant `:`, `;`, `?` et `!`, écrite comme une espace ordinaire dans les messages (`options :`) ; guillemets « … » ; pas d'anglicisme quand un mot français courant existe (*greffon* pour plugin, *jumelage* pour pairing).

## Documentation

Chaque page existe dans `docs/en/` et `docs/fr/` sous le même nom de fichier ; un test le vérifie. Mettre les deux à jour dans la même modification. En cas d'écart, la version anglaise de la spécification du protocole fait foi ; les autres pages n'ont pas de langue de référence.
