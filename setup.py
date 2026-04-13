from setuptools import setup, find_packages

setup(
    name="iv-agent",
    version="0.1.0",
    description="Autonomous reliability characterization AI agent for on-chip capacitor arrays",
    packages=find_packages(),
    python_requires=">=3.11",
    install_requires=[
        "numpy>=1.26.0",
        "matplotlib>=3.8.0",
        "pydantic>=2.5.0",
        "PyYAML>=6.0.1",
        "pandas>=2.1.0",
        "scipy>=1.11.0",
        "rich>=13.7.0",
        "click>=8.1.7",
    ],
    entry_points={
        "console_scripts": [
            "iv-agent=iv_agent.__main__:cli",
        ],
    },
)
