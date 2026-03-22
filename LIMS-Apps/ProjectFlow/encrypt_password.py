#!/usr/bin/env python3
import sys
try:
    from werkzeug.security import generate_password_hash
except ImportError:
    print("Werkzeug not found. Please install it by running: pip install Werkzeug")
    exit(1)

def create_hashed_password():
    """Takes a password as a command-line argument and prints its hash."""
    if len(sys.argv) != 2:
        print("Usage: python3 encrypt_password.py <password_to_encrypt>")
        return

    password = sys.argv[1]
    if not password:
        print("Password cannot be empty.")
        return

    hashed_password = generate_password_hash(password)
    
    print("\nEncryption successful!")
    print("Copy the following line and use it as the HASHED_PASSWORD value in your application:")
    print("-" * 70)
    print(hashed_password)
    print("-" * 70)

if __name__ == "__main__":
    create_hashed_password()
