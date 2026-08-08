from pathlib import Path

from setuptools import find_packages, setup

ROOT = Path(__file__).parent
README = (ROOT / "README.md").read_text(encoding="utf-8")

setup(
    name="subai-engine",
    version="1.0.0",
    description="Desktop app tự động hoá phụ đề và lồng tiếng AI cho video đa ngôn ngữ",
    long_description=README,
    long_description_content_type="text/markdown",
    author="SubAI Team",
    packages=find_packages(include=["src", "src.*", "server", "server.*", "desktop", "desktop.*"]),
    python_requires=">=3.11,<3.12",
    install_requires=[
        "PySide6-Essentials>=6.6.0",
        "requests>=2.31.0",
        "cryptography>=41.0.0",
    ],
    extras_require={
        "engine": [
            "torch>=2.1.0",
            "torchaudio>=2.1.0",
            "demucs>=4.0.1",
            "faster-whisper>=1.0.0",
            "TTS>=0.22.0",
            "soundfile>=0.12.1",
            "pyrubberband>=0.3.0",
            "yt-dlp>=2024.03.10",
        ],
        "server": [
            "fastapi>=0.110.0",
            "uvicorn>=0.28.0",
            "google-genai>=0.1.0",
            "pydantic>=2.6.0",
        ],
        "dev": ["pytest>=8.0.0", "pyinstaller>=6.3.0"],
    },
    entry_points={
        "console_scripts": ["subai-cli = src.main_pipeline:main"],
        "gui_scripts": ["subai-studio = desktop.app:main"],
    },
    classifiers=[
        "Environment :: X11 Applications :: Qt",
        "Programming Language :: Python :: 3.11",
        "Topic :: Multimedia :: Video",
    ],
)
