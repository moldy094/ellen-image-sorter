# ellen-sorter command
#   ellen-sorter run          the background thing the service runs
#   ellen-sorter scan         sort whatever is in the folder right now and quit
#   ellen-sorter sort FILE    sort specific files (they get moved into the library)
#   ellen-sorter sync         update the danbooru catalog
#   ellen-sorter index        rebuild the duplicate index
#   ellen-sorter gui          open the setup window
#   ellen-sorter test-notify  send a test notification

import sys
import shutil
import os

from . import config


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "gui"
    if cmd == "run":
        from . import sorter
        sorter.run()
    elif cmd == "scan":
        from . import sorter
        sorter.setup_logging()
        sorter.sort_everything_now(config.load())
    elif cmd == "sort":
        from . import sorter, library
        sorter.setup_logging()
        cfg = config.load()
        library.update_index(cfg["library"]["root"], set(cfg["library"]["ignore"]))
        for f in sys.argv[2:]:
            sorter.sort_one_safely(os.path.abspath(f), cfg)
    elif cmd == "sync":
        from . import catalog
        cfg = config.load()
        added = catalog.sync(cfg["library"]["character_tag"])
        print(f"done, {added} new posts, {catalog.count()} total")
    elif cmd == "index":
        from . import library
        cfg = config.load()
        added, gone = library.update_index(cfg["library"]["root"], set(cfg["library"]["ignore"]))
        print(f"done, {added} added, {gone} removed")
    elif cmd == "gui":
        from . import gui
        gui.main()
    elif cmd == "test-notify":
        from . import notify
        notify.send(config.load(), "ellen image sorter", "test notification, if you see this its working", error=True)
    else:
        print("unknown command:", cmd)
        print("commands: run, scan, sort FILE, sync, index, gui, test-notify")
        sys.exit(1)


if __name__ == "__main__":
    main()
