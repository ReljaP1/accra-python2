"""Python 2.7 install bounds shared by the pip manager and the manifests."""

PYTHON2_VERSION = "2.7"
PYTHON27_IMAGE = "python:2.7"
PYENV_VERSIONS = ("2.7.18", "2.7")
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

# numpy.distutils reads these names and skips a library when the value is None.
# Without that, a macOS build of the last Python 2.7 numpy selects Accelerate
# and passes -faltivec, which current clang rejects.
SOURCE_BUILD_ENV = {
    "ACCELERATE": "None",
    "ATLAS": "None",
    "BLAS": "None",
    "LAPACK": "None",
}

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
    "__builtin__",
    "exceptions",
    "_winreg",
    "repr",
    "test.test_support",
    "dummy_threading",
    "whichdb",
    "anydbm",
    "dbhash",
    "dumbdbm",
    "gdbm",
    "cgihttpserver",
    "docxmlrpcserver",
    "robotparser",
    "rfc822",
    "mimetools",
    "mimify",
    "multifile",
    "md5",
    "sha",
    "audiodev",
    "bastion",
    "rexec",
    "bsddb",
    "canvas",
    "cl",
    "dircache",
    "fpformat",
    "htmllib",
    "ihooks",
    "imputil",
    "linuxaudiodev",
    "new",
    "mutex",
    "posixfile",
    "pure",
    "sgmllib",
    "sunaudio",
    "statvfs",
    "sv",
    "toaiff",
    "timing",
    "xmllib",
    "aepack",
    "aetools",
    "aetypes",
    "applesingle",
    "buildtools",
    "cf",
    "cfmfile",
    "ic",
    "icglue",
    "icopen",
    "mactypes",
    "macerrors",
    "macfs",
    "macostools",
    "findertools",
    "gensuitemodule",
    "bundlebuilder",
    "quicktime",
    "miniae",
}
