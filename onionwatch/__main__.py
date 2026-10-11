"""`python -m onionwatch`"""
from onionwatch.app import main

if __name__ == "__main__":   # Onion Board imports every file of the add-on: don't start a second app
    main()
