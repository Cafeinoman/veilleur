# Security policy

*[Version française ci-dessous](#politique-de-sécurité)*

## Reporting a vulnerability

Please report vulnerabilities **privately**, through GitHub:
<https://github.com/Cafeinoman/veilleur/security/advisories/new>

Do not open a public issue or pull request for a vulnerability. Please include the affected version, the steps to reproduce the problem and its expected impact. Use fictitious data only: never send real secrets, pairing codes or reports.

Veilleur is maintained on a voluntary basis, so no response time is guaranteed. Fixes are published first, then the advisory, in agreement with the person who reported the problem.

## Supported versions

| Version | Security fixes |
|---|---|
| 0.1.x | yes |
| older | no |

## Scope

In scope: the server, the `veilleur-protocol` library, the `veilleur-receive` reference receiver, the protocol specification, and the deployment files in this repository.

Out of scope: third-party plugins and receiving tools, and limits the [threat model](docs/en/threat-model.md) already documents, such as the absence of forward secrecy.

---

# Politique de sécurité

## Signaler une faille

Signalez les failles **en privé**, par GitHub :
<https://github.com/Cafeinoman/veilleur/security/advisories/new>

N'ouvrez ni ticket ni *pull request* publics pour une faille. Indiquez la version concernée, les étapes pour reproduire le problème et son impact probable. Utilisez uniquement des données fictives : n'envoyez jamais de vrais secrets, codes de jumelage ou rapports.

Veilleur est maintenu bénévolement : aucun délai de réponse n'est garanti. Le correctif est publié d'abord, puis l'avis de sécurité, en accord avec la personne qui a signalé le problème.

## Versions suivies

| Version | Correctifs de sécurité |
|---|---|
| 0.1.x | oui |
| antérieures | non |

## Périmètre

Dans le périmètre : le serveur, la bibliothèque `veilleur-protocol`, le récepteur de référence `veilleur-receive`, la spécification du protocole et les fichiers de déploiement de ce dépôt.

Hors périmètre : les greffons et outils de réception de tiers, et les limites déjà décrites par le [modèle de menace](docs/fr/threat-model.md), comme l'absence de confidentialité persistante.
