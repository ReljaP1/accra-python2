from setuptools import find_packages, setup

setup(
    name="example_package",
    version="0.1.0",
    description="A simple example package",
    packages=find_packages(),
    python_requires=">=2.7",
    install_requires=[
        "requests>=2.28",
        "numpy>=1.8",
        "click>=8.1",
    ],
)
