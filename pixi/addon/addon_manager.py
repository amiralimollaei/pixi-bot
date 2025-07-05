import os
import sys
import glob
import logging
import importlib.util

# constants

ADDON_DIR = "addons"


class AddonManager:
    def __init__(self, bot):
        self.bot = bot
        self.addons_dir = os.path.abspath(ADDON_DIR)
        self.addons = {}

    def load_addons(self):
        if not os.path.isdir(self.addons_dir):
            logging.warning(f"Addons directory '{self.addons_dir}' not found.")
            return

        for addon_path in glob.glob(os.path.join(self.addons_dir, "*_addon")):
            if not os.path.isdir(addon_path):
                continue
            basename = os.path.basename(addon_path)
            addon_name = basename
            if not addon_name.startswith("_"):
                self.load_addon(addon_name, addon_path)

    def load_addon(self, name, path):
        sys.path.append(os.path.dirname(path))

        addon_file = os.path.join(path, "__init__.py")
        if not os.path.isfile(addon_file):
            logging.warning(f"Addon '{name}' does not have an __init__.py file.")
            return

        self.load_addon_file(name, addon_file)

    def load_addon_file(self, name, path):
        logging.info(f"Loading addon: {name} from {path}")
        spec = importlib.util.spec_from_file_location(name, path, submodule_search_locations=[])
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(module)
                if hasattr(module, "register"):
                    module.register(self.bot, logging.getLogger(name))
                    self.addons[name] = module
                else:
                    logging.warning(f"Addon '{name}' does not have a valid register function.")
            except Exception as e:
                logging.exception(f"Failed to load addon '{name}'")
        else:
            logging.error(f"Could not load addon '{name}': Invalid module specification.")

    def get_addon(self, name):
        return self.addons.get(name)
