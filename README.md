# ellen image sorter

god this is so fucking stupid

you drop ellen joe pictures and videos into a folder and this sorts them for you in the background. it works out the pose, finds who drew it, grabs the highest quality version it can find, gets rid of duplicates and moves everything into the right folder.

it runs as a systemd service so you set it up once and forget about it. theres a small setup window for the settings and it pops up a notification if something goes wrong.

## what it does

- watches one folder. anything new that lands in the top of it gets sorted
- sorts by pose into portraits, full body, sitting, lying down, from behind, action, with others and misc
- names files after the artist, like `portraits/tanjwi 3.jpg`. if it cant find one its `unknown 12.jpg`
- lewd stuff goes in `goonery/` and ai generated stuff goes in `ai/`. you can turn both off
- looks for a bigger version of the picture on pixiv, twitter and danbooru and swaps it in if it finds one
- checks every new file against everything you already have so you dont end up with the same picture twice
- works on videos and gifs too
- anything it cant handle goes in `_needs_review/` and you get a notification about it

## what the folder ends up like

```
ellen sharkhive/
├── portraits/
├── full body/
├── sitting/
├── lying down/
├── from behind/
├── action/
├── with others/
├── misc/
├── goonery/        same pose folders inside
├── ai/             same pose folders inside
├── _needs_review/
└── _sort_manifest.csv
```

`_sort_manifest.csv` keeps track of every file it moved, where it went, who drew it and how it figured that out. so if something ends up in a weird spot you can always find where it came from.

## install

you need linux with systemd, python 3.11 or newer and ffmpeg. made it on arch with kde but it should work on anything with a normal desktop.

```
git clone https://github.com/moldy094/ellen-image-sorter
cd ellen-image-sorter
./install.sh
```

if you want it to read signatures off pictures too, run `./install.sh --ocr` instead. its about 1GB bigger because of torch.

after that open ellen image sorter from your app menu, pick your folder, hit save then hit start. tick start on login if you want it running all the time.

the first time it starts it builds a list of every ellen post on danbooru (around 10k) so it can match pictures without searching online every time. that takes about 10 minutes. after that it only grabs new posts every 12 hours.

it also downloads the tagger model the first time it needs it, about 1.2GB. it unloads it from RAM when its been sitting idle for a while.

## how it finds the artist

it tries these in order and stops at the first one that knows:

1. the file name. pixiv saves (`123456789_p0.png`) and danbooru downloads have the artist or the post id in them
2. danbooru, by the files md5
3. the local danbooru list, by comparing the picture itself. this catches most stuff even if its been resized or recompressed
4. saucenao, if you put a key in. this one searches twitter and pixiv too so it finds a lot more. you can get a free key at https://saucenao.com/user.php?page=search-api
5. the signature on the picture, if you installed it with `--ocr`. it looks for @handles and patreon links
6. info stored inside the file itself

artist names come out the same way danbooru writes them, so the same artist always ends up with the same name no matter where the picture came from.

## ai detection

it puts stuff in `ai/` if danbooru tags it as ai, if pixiv says its ai, if the file has generator settings saved inside it, or if the signature is an obvious ai account. its not perfect and some will slip through, so if you care a lot have a look through every now and then.

## commands

the gui does most of this but theres a command too:

```
ellen-sorter gui          open the setup window
ellen-sorter run          what the service runs
ellen-sorter scan         sort whatever is in the folder right now
ellen-sorter sort FILE    sort specific files into the library
ellen-sorter sync         update the danbooru list now
ellen-sorter index        rebuild the duplicate index
ellen-sorter test-notify  send a test notification
```

it lives at `~/.local/share/ellen-sorter/venv/bin/ellen-sorter`.

## settings

theyre in `~/.config/ellen-sorter/config.toml`. the gui writes this file and the service picks up changes on its own, no restart needed.

| setting | what it does |
| --- | --- |
| `library.root` | the folder it watches |
| `library.character_tag` | danbooru tag for the list, `ellen_joe` by default |
| `library.ignore` | folders and files in the root it leaves alone |
| `sorting.goonery` | `off`, `lewd` (questionable and explicit) or `suggestive` (also bikinis and that kind of thing) |
| `sorting.separate_ai` | put ai stuff in its own folder |
| `sorting.upgrade_quality` | look for bigger versions |
| `sorting.duplicates` | `trash` keeps the best copy, `keep` keeps both |
| `sources.saucenao_key` | your saucenao key |
| `sources.ocr` | read signatures, needs the `--ocr` install |
| `notify.desktop` | popups when something goes wrong |
| `notify.on_success` | also popup every time something gets sorted |
| `notify.webhook_url` | a discord webhook or ntfy url if you want pings on your phone too |

## good to know

- it never deletes anything. duplicates and files it replaced with a bigger version go to your trash
- if two pictures look really close but might be different (like a translated version) it keeps both and tells you
- logs are in `~/.local/state/ellen-sorter/ellen-sorter.log` or `journalctl --user -u ellen-sorter`
- if your folder is on another drive and it isnt mounted you get a notification and it waits for it to come back

## uninstall

```
./uninstall.sh
```

that leaves your settings and pictures alone. `./uninstall.sh --all` gets rid of the settings and the danbooru list too.

## license

MIT
