import sys
import os

# добавляем корень проекта в PYTHONPATH
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT_DIR)

from client.main import main

if __name__ == "__main__":
    main()
