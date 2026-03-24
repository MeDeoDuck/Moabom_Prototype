#!/usr/bin/env python3
"""
YouTube Product Analysis Service
Comprehensive Setup & Verification Script

Run this to verify your installation is complete and correct.
"""

import os
import sys
from pathlib import Path

def check_file(path, description):
    """Check if a file exists."""
    if Path(path).exists():
        size = Path(path).stat().st_size
        print(f"✅ {description:<40} ({size:,} bytes)")
        return True
    else:
        print(f"❌ {description:<40} MISSING")
        return False

def check_dir(path, description):
    """Check if a directory exists."""
    if Path(path).exists():
        print(f"✅ {description:<40} (directory)")
        return True
    else:
        print(f"❌ {description:<40} MISSING")
        return False

def check_dependency(module, name):
    """Check if a Python module is installed."""
    try:
        __import__(module)
        print(f"✅ {name:<40} installed")
        return True
    except ImportError:
        print(f"❌ {name:<40} NOT INSTALLED")
        return False

def check_env_var(var, description):
    """Check if an environment variable is set."""
    if os.getenv(var):
        print(f"✅ {description:<40} SET")
        return True
    else:
        print(f"⚠️  {description:<40} NOT SET (required for YouTube API)")
        return False

def main():
    print("\n" + "="*70)
    print("🎬 YouTube Product Analysis Service - Setup Verification")
    print("="*70 + "\n")
    
    all_good = True
    
    # Check project files
    print("📄 PROJECT FILES")
    print("-" * 70)
    files_to_check = [
        ("main_youtube_analysis.py", "Main application file"),
        ("requirements.txt", "Python dependencies"),
        (".env", "Environment configuration"),
        (".gitignore", "Git ignore rules"),
        ("docker-compose.yml", "Docker Compose config"),
        ("Dockerfile", "Docker image config"),
        ("setup.sh", "Linux/macOS setup script"),
        ("setup.bat", "Windows setup script"),
    ]
    
    for file, desc in files_to_check:
        all_good = check_file(file, desc) and all_good
    
    # Check documentation files
    print("\n📚 DOCUMENTATION FILES")
    print("-" * 70)
    docs_to_check = [
        ("README_YOUTUBE_SERVICE.md", "Main documentation"),
        ("USAGE_EXAMPLES.md", "Usage guide with examples"),
        ("DELIVERY_SUMMARY.md", "Project summary"),
        ("DOCKER_GUIDE.md", "Docker deployment guide"),
        ("TESTING_GUIDE.md", "Testing guide"),
        ("INDEX.md", "Documentation index"),
    ]
    
    for file, desc in docs_to_check:
        all_good = check_file(file, desc) and all_good
    
    # Check directories
    print("\n📁 DIRECTORIES")
    print("-" * 70)
    dirs_to_check = [
        ("templates", "HTML templates"),
    ]
    
    for dir, desc in dirs_to_check:
        if not Path(dir).exists():
            print(f"⚠️  {desc:<40} (will be created on first run)")
        else:
            check_dir(dir, desc)
    
    # Check Python dependencies
    print("\n🐍 PYTHON DEPENDENCIES")
    print("-" * 70)
    deps_to_check = [
        ("fastapi", "FastAPI"),
        ("uvicorn", "Uvicorn"),
        ("psycopg2", "psycopg2-binary"),
        ("httpx", "httpx"),
        ("jinja2", "Jinja2"),
        ("dotenv", "python-dotenv"),
    ]
    
    deps_missing = []
    for module, name in deps_to_check:
        if not check_dependency(module, name):
            deps_missing.append(name)
            all_good = False
    
    if deps_missing:
        print(f"\n💡 Install missing dependencies:")
        print(f"   pip install -r requirements.txt")
    
    # Check environment variables
    print("\n⚙️  ENVIRONMENT VARIABLES")
    print("-" * 70)
    
    db_url = os.getenv("DATABASE_URL")
    api_key = os.getenv("YOUTUBE_API_KEY")
    
    if db_url:
        # Mask password in URL
        masked = db_url.replace(db_url.split("@")[0] if "@" in db_url else "", "***://***")
        print(f"✅ {'DATABASE_URL':<40} SET")
    else:
        print(f"❌ {'DATABASE_URL':<40} NOT SET")
        all_good = False
    
    if api_key:
        # Mask API key
        masked = api_key[:10] + "..." if len(api_key) > 10 else "***"
        print(f"✅ {'YOUTUBE_API_KEY':<40} SET ({masked})")
    else:
        print(f"⚠️  {'YOUTUBE_API_KEY':<40} NOT SET (required for YouTube features)")
    
    # Check system requirements
    print("\n🖥️  SYSTEM REQUIREMENTS")
    print("-" * 70)
    
    import platform
    py_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    print(f"✅ {'Python version':<40} {py_version}")
    print(f"✅ {'Operating System':<40} {platform.system()}")
    
    # Summary
    print("\n" + "="*70)
    if all_good and deps_missing:
        print("⚠️  INSTALLATION INCOMPLETE")
        print("\nNext steps:")
        print("1. Install dependencies: pip install -r requirements.txt")
        print("2. Update .env with DATABASE_URL and YOUTUBE_API_KEY")
        print("3. Run: python main_youtube_analysis.py")
    elif all_good:
        print("✅ INSTALLATION COMPLETE")
        print("\nNext steps:")
        print("1. Update .env with DATABASE_URL and YOUTUBE_API_KEY")
        print("2. Ensure PostgreSQL is running")
        print("3. Run: python main_youtube_analysis.py")
        print("4. Open: http://localhost:8000")
    else:
        print("❌ INSTALLATION INCOMPLETE")
        print("\nPlease check the missing files/dependencies above")
    
    print("\n📖 Documentation")
    print("-" * 70)
    print("Start here:      README_YOUTUBE_SERVICE.md")
    print("How to use:      USAGE_EXAMPLES.md")
    print("Deployment:      DOCKER_GUIDE.md")
    print("Testing:         TESTING_GUIDE.md")
    print("Full index:      INDEX.md")
    print("\n" + "="*70 + "\n")
    
    return 0 if (all_good and not deps_missing) else 1

if __name__ == "__main__":
    sys.exit(main())
