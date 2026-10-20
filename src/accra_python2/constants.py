"""Python 2.7 install bounds shared by the pip manager and the manifests."""

PYTHON2_VERSION = "2.7"
# Last virtualenv that can still create a CPython 2.7 environment.
VIRTUALENV_SPEC = "virtualenv==20.21.1"
VENV_DIR = ".venv"
VENV_PIP = f"{VENV_DIR}/bin/pip"
IGNORE_REQUIRES_PYTHON = "--ignore-requires-python"

BOOTSTRAP_SPECS = (
    "pip<21",
    "setuptools<45",
    "wheel<0.35",
)

# Last releases that still install on CPython 2.7.
LEGACY_PINS = {
    "numpy": "numpy<1.17",
    "scipy": "scipy<1.3",
    "pandas": "pandas<0.25",
    "scikit-learn": "scikit-learn<0.21",
    "sklearn": "scikit-learn<0.21",
    "matplotlib": "matplotlib<3",
}

# Import names that are part of the Python 2 standard library.
STDLIB_ALIASES = {
    "cpickle",
    "cstringio",
    "stringio",
    "configparser",
    "queue",
    "urlparse",
    "urllib2",
    "cookielib",
    "httplib",
    "htmlentitydefs",
    "commands",
    "copy_reg",
    "markupbase",
    "thread",
    "dummy_thread",
    "xmlrpclib",
    "simplehttpserver",
    "basehttpserver",
    "simplexmlrpcserver",
    "socketserver",
    "userdict",
    "userlist",
    "userstring",
}
