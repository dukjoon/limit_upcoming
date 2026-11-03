from setuptools import setup, find_packages

setup(
    name="limit-upcoming",
    version="0.1.0",
    description="Deterministic local evidence bundle generator and proactive usage limit handoff tool",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    entry_points={
        "console_scripts": [
            "limit-upcoming = limit_upcoming.cli:main",
        ],
    },
    python_requires=">=3.9",
)
