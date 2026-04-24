import os

from .converter import main

os.umask(0o007)
main()
