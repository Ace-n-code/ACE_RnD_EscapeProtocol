import sys
import importlib
import json
import os
import requests
import subprocess

maze_files = [
    r"src/mazes/MAZE_NOT_FOUND.json",
    r"src/mazes/Controller.json",
    r"src/mazes/Kinich.json",
    r"src/mazes/pengwin.json",
    r"src/mazes/FC Barcelona.json",
    r"src/mazes/GEASS.json",
    r"src/mazes/bleach.json",
    r"src/mazes/SKULL_MAZE.json",
    r"src/mazes/cyno.json",
    r"src/mazes/rocket ship.json",
    r"src/mazes/Astrobot.json",
    r"src/mazes/Pikachu.json",
    r"src/mazes/sortinghat hp.json",
    r"src/mazes/Luffy.json",
    r"src/mazes/snowflake.json",
    r"src/mazes/Python.json",
    r"src/mazes/TechnicalDay.json",
    r"src/mazes/Squirtle.json",
    r"src/mazes/mario.json",
    r"src/mazes/WARDEN.json"
]


def install_module(package_name):
    """Install a missing Python package using pip."""
    try:
        print(f"⬇️ Installing missing package: {package_name}")
        subprocess.check_call([sys.executable, "-m", "pip", "install", package_name])
        print(f"✅ Successfully installed '{package_name}'.")
        return True
    except Exception as e:
        print(f"❌ Failed to install '{package_name}': {e}")
        return False


def check_python_version():
    print("🧠 Checking Python version...")
    if sys.version_info < (3, 8):
        print(f"❌ Python {sys.version.split()[0]} detected. Please use 3.8 or higher.")
        return False
    print(f"✅ Python {sys.version.split()[0]} is compatible.")
    return True


def check_module(module_name, package_name=None):
    """Check if a module is available, auto-install if not."""
    package_name = package_name or module_name
    try:
        importlib.import_module(module_name)
        print(f"✅ Module '{module_name}' found.")
        return True
    except ImportError:
        print(f"❌ Module '{module_name}' is missing.")
        return install_module(package_name)


def check_turtle_graphics():
    print("🎨 Testing turtle graphics window...")
    try:
        import turtle
        screen = turtle.Screen()
        screen.title("Graphics Test")
        turtle.hideturtle()
        screen.update()
        screen.bye()
        print("✅ Turtle graphics working fine.")
        return True
    except Exception as e:
        print(f"❌ Turtle graphics failed: {e}")
        return False


def check_maze_files():
    print("🗂️ Checking for maze files...")
    found = False
    for file in maze_files:
        try:
            with open(file, "r") as f:
                json.load(f)
            print(f"✅ Valid maze file found: {file}")
            found = True
        except json.JSONDecodeError:
            print(f"⚠️ {file} is not a valid JSON maze file.")
        except FileNotFoundError:
            print(f"⚠️ File not found: {file}")
        except Exception as e:
            print(f"⚠️ Error reading {file}: {e}")
    if not found:
        print("❌ No valid maze files found in the directory.")
    return found


def check_api_connection(test_url="https://www.google.com",
                         api_url="https://ace-rnd-escapeprotocol.onrender.com/leaderboard"):
    print("🌐 Checking internet and API connectivity...")
    try:
        # Step 1: General internet check
        r = requests.get(test_url, timeout=5)
        if r.status_code == 200:
            print("✅ Internet connection working.")
        else:
            print(f"⚠️ Internet access seems unstable (Status {r.status_code})")

        # Step 2: API connection
        if api_url:
            print(f"🔗 Checking API connection: {api_url}")
            api_resp = requests.get(api_url, timeout=10)
            if api_resp.status_code == 200:
                print("✅ API connection successful.")
            else:
                print(f"⚠️ API responded with status: {api_resp.status_code}")
        return True

    except requests.exceptions.RequestException as e:
        print(f"❌ Network/API check failed: {e}")
        return False


def run_all_checks():
    print("🔍 Running Maze System Check...\n")

    # Pre-check: Ensure pip itself is available
    check_module("pip")

    checks = [
        check_python_version(),
        check_module("tkinter"),
        check_module("turtle"),
        check_module("json"),
        check_module("requests"),
        check_turtle_graphics(),
        check_maze_files(),
        check_api_connection(),
    ]

    print("\n📊 Summary:")
    if all(checks):
        print("✅ All systems operational! You’re ready to play.")
    else:
        print("⚠️ Some checks failed. Please fix the above issues before running the maze.")


if __name__ == "__main__":
    run_all_checks()
