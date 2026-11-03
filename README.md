# G-Bible
### Your Bible. Your Library. Your Study.

**A complete Bible study workspace that lives on your computer.**

G-Bible is a free, open-source Bible study application designed to bring Scripture, study tools, reference materials, and personal notes together in one place.

Read the Bible, explore its meaning, compare translations, research historical context, and build your own personal study library — all through a single, customizable workspace.

No account required. No subscription. No cloud dependency. Just you, your Bible, and the tools to study it more deeply.

---

> **⚠️ Beta Notice**
>
> G-Bible is currently in beta. Most features are functional, but some may not work as expected, and others are still under development.
>
> This is a hobby project developed in my spare time, so updates and new features may take a little while. Your patience and understanding are greatly appreciated!
>
> Feedback, bug reports, and suggestions are always welcome and help make G-Bible better for everyone. Thank you for your support!

---

## Explore Scripture. Build Your Understanding.

Whether you're reading a daily passage, researching a difficult verse, preparing a lesson, or exploring the original languages, G-Bible gives you a flexible environment for studying Scripture.

### A Workspace Built for Bible Study

Go beyond a single Bible window. Arrange your study materials side by side, open multiple passages in separate panes, and link your resources together so they follow your reading.

Read a passage in one pane while consulting a commentary, lexicon, or reference book in another. Resize your workspace, organize your tabs, and save layouts that fit the way you study.

### A Library That Grows With You

Build a personal collection of Bibles, commentaries, dictionaries, maps, and other study resources.

G-Bible includes a Store of freely redistributable study materials that you can install directly into your library. You can also import your own EPUBs and compatible Bible modules.

Your library is yours to organize, expand, and use.

### Search Beyond the Page

Find passages, words, and topics across your installed resources with G-Bible's powerful search tools.

Search Scripture and reference materials, use filters to narrow your results, and explore Strong's numbers to help investigate biblical words and their meanings.

### Study With Context

Explore Scripture through a collection of study guides and reference tools, including:

- Biblical timelines and maps
- Genealogies and Gospel harmonies
- Outlines and other study resources
- Concordance and word-reference tools

G-Bible brings these tools together so you can move from reading a passage to exploring its context without losing your place.

### Make Your Study Personal

Your study doesn't have to end when you close the app.

Create notes, highlight verses, save clips, and organize your discoveries with tags. Build reading plans, maintain prayer lists, and practice Scripture memorization with a spaced-repetition system.

Your personal study materials stay on your computer.

---

## Everything in One Place

G-Bible brings together the tools you need for a more organized and meaningful study experience.

| Feature | What it does |
|---|---|
| Home | Today's reading, reading plans, prayer list, notes, and highlights |
| Workspace | Multi-pane Bible reading, linked resources, tabs, and saved layouts |
| Search | Search installed resources, with filters and Strong's number support |
| Guides | Timelines, maps, genealogies, Gospel harmonies, and outlines |
| Library | Manage your installed Bibles, books, and reference materials |
| Notes & Highlights | Keep personal study notes and highlights connected to Scripture |
| Memorization | Practice verses using spaced repetition |
| Sync | Synchronize notes and progress through a folder, WebDAV, or Nextcloud |
| AI Assistant | Optional AI assistance using a provider you configure |
| Read Aloud | Listen to Scripture with optional voice installation |

---

## Get Started

G-Bible is designed to be easy to run on your own computer.

### Linux: The Easiest Way to Get Started

Want to get started with G-Bible on Linux without installing Python or setting up dependencies?

**Download the G-Bible 0.9.6 AppImage.** It comes with everything you need to run the application, so there's no complicated setup required.

1. Download the G-Bible 0.9.6 AppImage.
2. Make the file executable in your file manager, or run:

   ```bash
   chmod +x "G-Bible 0.9.6.AppImage"
   ```

3. Double-click the AppImage to launch G-Bible, or run it from the terminal:

   ```bash
   ./"G-Bible 0.9.6.AppImage"
   ```

#### Enable Read Aloud

The AppImage includes the Read Aloud voice installation files, so you don't need to download them separately.

To install the voice:

1. Open G-Bible.
2. Go to **Settings → Read Aloud Settings**.
3. Click **Install** and allow the installation to finish.

Once installed, you're ready to listen to Scripture using G-Bible's Read Aloud feature.

That's it! No Python setup, no dependency hunting, and no complicated installation process. Just download, launch, and start studying.

### Everyone Else

#### Requirements

- Python 3.11 or newer
- A modern web browser
- Internet access for the initial download of study materials, if desired

No Python package installation or separate build step is required for the standard launch.

#### 1. Download G-Bible

Download the project and extract the ZIP file, or clone the repository:

```bash
git clone https://github.com/blackclover5/G-Bible.git
cd G-Bible
```

If you downloaded the ZIP file instead, open a terminal inside the extracted project folder.

#### 2. Launch the App

Run:

```bash
python3 run.py
```

G-Bible will start its local server. Open the address printed in your terminal, usually:

```text
http://127.0.0.1:8777
```

You can now use G-Bible in your browser.

#### 3. Set Up Your Library

On the first launch, G-Bible offers a recommended collection of Bibles, commentaries, maps, and reference materials.

Accept the recommended collection to download the resources, or skip this step and install materials later through the Store.

Once your resources are installed, you can study offline.

#### 4. Start Studying

Open Workspace to begin reading Scripture. Use Search to explore your library, Guides to investigate biblical context, and the other tools to organize your study.

Your personal notes, highlights, and reading progress will be available the next time you launch G-Bible.

---

## Designed for Your Computer

G-Bible is built around local-first Bible study.

Your library, notes, highlights, and reading progress are stored on your own machine. You don't need to create an account or rely on a cloud service to use the application.

Once you have installed your resources, G-Bible can work offline.

Network access is used when you choose to download library materials, synchronize your data, or use an AI provider that you configure.

### Optional Features

**Read Aloud:** Install the voice directly within G-Bible by going to **Settings → Read Aloud Settings → Install**.

This works for both the Python version and the Linux AppImage.

If you need to install the voice manually, you can also run:

```bash
python3 tools/install_voice.py
```

**AI Assistant:** The AI Assistant is optional and disabled until you configure your own provider.

**Synchronization:** If you want to use G-Bible across multiple computers, you can configure synchronization through a folder, WebDAV, or Nextcloud.

---

## Privacy and Ownership

G-Bible is designed to keep your personal study personal.

- No account is required.
- No telemetry or analytics are built into the app.
- Your personal study data stays on your computer unless you choose to synchronize it.
- Network connections are used for features you explicitly choose to use.

Your Bible study should belong to you.

---

## Coming Soon: Android & Windows

G-Bible is growing!

I'm planning to bring G-Bible to Android and Windows, making it possible to enjoy your personal Bible study workspace on even more devices.

The goal is to bring the same powerful study tools, personal library, and customizable experience to these new platforms.

More details coming soon!

---

## Troubleshooting

**The app won't start**

Make sure Python 3.11 or newer is installed. Run `python3 run.py` from the project folder and check the terminal for error messages.

**The default port is already in use**

Launch G-Bible on another port:

```bash
python3 run.py --port 8899
```

Then open:

```text
http://127.0.0.1:8899
```

**Newly installed resources aren't appearing**

Restart G-Bible. The library index is updated when the application launches.

**Can I use G-Bible without internet access?**

Yes. Once your Bible translations and reference materials are installed, you can use them offline. Downloading additional materials, synchronization, and AI features may require an internet connection.

**How do I start over?**

Use About → Reset G-Bible inside the application, or run:

```bash
./reset-gbible
```

from the project folder.

---

## Built for Bible Study. Open to Everyone.

G-Bible is free and open source, released under the MIT License.

You are free to use, study, modify, and share the application under the terms of that license.

Whether you are a new reader, a lifelong student of Scripture, or someone building a personal reference library, G-Bible is designed to give you the tools to explore the Bible on your own terms.

**G-Bible — Your Bible. Your Library. Your Study.**
