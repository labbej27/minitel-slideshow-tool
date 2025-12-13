# Minitel Slideshow Tool  
**Convertisseur + Serveur Slideshow + Client WebSocket↔Série (tout-en-un)**  

Interface graphique Tkinter permettant :  
- la **conversion d’images** en fichiers **.vdt** optimisés (encodeur intégré, compatible *pic2jpeg2vdt*)
- un **serveur local WebSocket** pour diaporamas (start/stop/reset indépendants)
- un **client WebSocket ↔ port série** (Minitel)
- une liste de serveurs prédéfinis + saisie manuelle
- un temps d’affichage paramétrable
- prévisualisation hex optionnelle

---

## Fonctionnalités principales

### Conversion d’images → `.vdt`
- Redimensionnement automatique adapté Minitel (320×240 max)
- Encodage JPEG optimisé ou qualité fixe
- Génération des blocs VDT (header + chunks)
- Prévisualisation hex des premiers octets

### Serveur Slideshow WebSocket
- Diffusion continue d’un dossier de `.vdt`
- Serveur en thread dédié
- Commandes start/stop sécurisées

### Client WebSocket ↔ Port série
- Pont bidirectionnel avec keep-alive
- Support de `wss://` via SSL permissif
- Gestion vitesse, parité, databits, stopbits

### Interface graphique Tkinter
- Sélection de serveur prédéfini ou manuel
- Sélection de dossier images et dossier VDT
- Logs détaillés
- Détection automatique des ports série

---
## Installation

### 1. Cloner le dépôt

```sh
git clone https://github.com/labbej27/minitel-slideshow-tool.git
cd minitel-slideshow-tool
```

### 2. Installer les dépendances Python

Avec un environnement virtuel (recommandé) :

```sh
python3 -m venv venv
# Linux / macOS
source venv/bin/activate
# Windows (PowerShell)
venv\Scripts\Activate.ps1
# Windows (cmd)
venv\Scripts\activate.bat
```

Installer les dépendances :

```sh
pip install -r requirements.txt
```

- Note : Tkinter est déjà inclus dans Python sur Windows et macOS, et sur la plupart des distributions Linux.

## Utilisation
### 1. Lancer l’outil
python3 minitel_slideshow_tool.py

## 2. Convertir des images
- Choisir un dossier d’images

- Choisir un dossier de sortie

- Cliquer Convert Images

## 3. Lancer un serveur Slideshow
- Mettre des .vdt dans le dossier sélectionné

- Définir la durée par image

- Cliquer Start Slideshow Server

- Le serveur écoute par défaut sur :
ws://0.0.0.0:8765

## Se connecter à un serveur WebSocket via Minitel
- Choisir un serveur prédéfini ou entrer une URL

- Sélectionner le port série

- Cliquer Connecter & Enjoy


---

# Compilation en exécutable (standalone)

- L’outil peut être compilé en exécutable autonome (sans Python requis sur la machine cible) grâce à PyInstaller.

## Prérequis

- Python 3.14 recommandé

- pip à jour

## Système :

- Installer PyInstaller :

```sh
pip install pyinstaller
```

## Compilation simple

- Depuis la racine du projet :

```sh
pyinstaller --onefile --windowed minitel_slideshow_tool.py
```

## Options utilisées

```sh
--onefile : génère un seul fichier exécutable

--windowed : supprime la console (recommandé pour Tkinter)
```

- L’exécutable sera généré dans :

- dist/

## Compilation Windows (recommandée)
```sh
pyinstaller ^
  --onefile ^
  --windowed ^
  --name "MinitelSlideshowTool" ^
  minitel_slideshow_tool.py
```

## Résultat :

 - dist/MinitelSlideshowTool.exe

## Compilation Linux
```sh
pyinstaller \
  --onefile \
  --windowed \
  --name minitel-slideshow-tool \
  minitel_slideshow_tool.py
```

## L’exécutable est spécifique à l’OS :

- Un .exe Windows doit être compilé sous Windows, idem pour Linux/macOS.

## Compilation macOS
```sh
pyinstaller \
  --onefile \
  --windowed \
  --name MinitelSlideshowTool \
  minitel_slideshow_tool.py
```

- Sur macOS :

- L’application peut être bloquée par Gatekeeper

- Utiliser clic droit → Ouvrir au premier lancement

## Inclusion des dépendances

- PyInstaller détecte automatiquement :

- tkinter

- Pillow

- pyserial

- websockets

Si nécessaire (rare), forcer les imports :

```sh
pyinstaller --onefile --windowed \
  --hidden-import=serial \
  --hidden-import=serial.tools.list_ports \
  minitel_slideshow_tool.py
  ```

## Débogage en cas de problème

- Compiler avec console pour voir les erreurs :
```sh
pyinstaller --onefile minitel_slideshow_tool.py
```

- Lancer ensuite depuis un terminal pour lire les logs.

#### Ports série – Permissions
- Linux
Ajouter l’utilisateur au groupe dialout :

```bash
sudo usermod -a -G dialout $USER
```

Puis redémarrer la session.

#### Licence
Projet libre – utilisation et modification autorisées.

Ce projet a été développé à des fins personnelles et éducatives,
en s’inspirant de projets existants de la communauté Minitel.

## Crédits / Sources

Ce projet s’appuie sur ou s’inspire des travaux suivants :

- **websocket2minitel** par @cquest  
  https://github.com/cquest/websocket2minitel
  

- Code et expérimentations de @NathaanTFM  
  https://gist.github.com/NathaanTFM/2ca8687f1352b9d840d4f5efc941dd98
---
