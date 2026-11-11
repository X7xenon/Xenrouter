from setuptools import setup, find_packages

setup(
    name="xenrouter",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "fastapi>=0.110.0",
        "uvicorn>=0.28.0",
        "httpx>=0.27.0",
        "pydantic>=2.6.0",
        "rich>=13.7.0",
        "typer>=0.9.0",
        "pyyaml>=6.0.1"
    ],
    entry_points={
        "console_scripts": [
            "xenrouter = xenrouter.cli:main",
        ],
    },
)
