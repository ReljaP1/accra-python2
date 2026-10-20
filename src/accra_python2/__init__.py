from .language import Python2
from .pip_env import Pip
from .requirements_txt import Requirements_txt
from .setup_cfg import Setup_cfg
from .setup_py import Setup_py

__all__ = ["Pip", "Python2", "Requirements_txt", "Setup_cfg", "Setup_py"]


def main() -> None:
    print("python2")
