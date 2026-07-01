import os
from pathlib import Path
from typing import IO


def get_resource_path(filename) -> str:
    return os.path.join(PixiPaths.resources(), filename)


def open_resource(filename: str, mode: str) -> IO:
    return open(os.path.join(PixiPaths.resources(), filename), mode=mode, encoding="utf-8")


class PixiPaths:
    _root = Path("~/.pixi")

    # ---- configuration ----
    @classmethod
    def set_root(cls, root: str | Path) -> None:
        cls._root = Path(root)

    @classmethod
    def root(cls) -> Path:
        return cls._root.expanduser()

    # ---- paths ----
    @classmethod
    def addons(cls) -> Path:
        return cls.root() / "addons"

    @classmethod
    def datasets(cls) -> Path:
        return cls.root() / "datasets"

    @classmethod
    def resources(cls) -> Path:
        return cls.root() / "resources"

    @classmethod
    def userdata(cls) -> Path:
        return cls.root() / "userdata"

    @classmethod
    def cache(cls) -> Path:
        return cls.root() / "cache"


# if the PixiPaths.RESOURCES folder doesn't exist, we should copy all our default assets in there when the module is imported
if __package__ is not None:
    import importlib.resources
    import shutil

    MODULE_PATH = importlib.resources.files(__package__)
    RESOURCES_PATH = str(MODULE_PATH / "resources")

    def copy_if_absent(src: str, dst: str, *, follow_symlinks: bool = True):
        if os.path.exists(dst):
            if os.path.isdir(dst):
                raise FileExistsError(f"directory exists with the same name as destination the file: {dst}")
            return
        shutil.copy2(src, dst, follow_symlinks=follow_symlinks)

    def copy_default_resources():
        os.makedirs(PixiPaths.resources(), exist_ok=True)
        shutil.copytree(RESOURCES_PATH, PixiPaths.resources(), dirs_exist_ok=True, copy_function=copy_if_absent)
