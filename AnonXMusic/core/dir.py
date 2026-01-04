import os
import shutil

from ..logging import LOGGER


def dirr():
    for file in os.listdir():
        if file.endswith(".jpg"):
            os.remove(file)
        elif file.endswith(".jpeg"):
            os.remove(file)
        elif file.endswith(".png"):
            os.remove(file)

    if "downloads" in os.listdir():
        try:
            shutil.rmtree("downloads")
        except Exception:
            pass
    os.makedirs("downloads", exist_ok=True)
    
    if "cache" in os.listdir():
        try:
            shutil.rmtree("cache")
        except Exception:
            pass
    os.makedirs("cache", exist_ok=True)

    LOGGER(__name__).info("Directories Updated.")
