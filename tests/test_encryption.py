import pytest
from serviceBot.services.encryption import encrypt_key, decrypt_key, aes_256_ctr

def test_encryption_roundtrip():
    """Verify encrypt_key and decrypt_key produce the correct round-trip results."""
    secret = "my-super-secret-token-12345!"
    encrypted = encrypt_key(secret)
    assert encrypted != secret
    assert isinstance(encrypted, str)
    
    decrypted = decrypt_key(encrypted)
    assert decrypted == secret

def test_encryption_empty_and_none():
    """Verify handling of empty strings and None values."""
    assert encrypt_key("") == ""
    assert decrypt_key("") == ""
    assert encrypt_key(None) == ""
    assert decrypt_key(None) == ""

def test_aes_256_ctr_raw():
    """Verify raw CTR block processing directly."""
    key = b"1" * 32
    nonce = b"2" * 8
    data = b"Hello world, testing raw encryption!"
    
    encrypted = aes_256_ctr(data, key, nonce)
    assert encrypted != data
    
    decrypted = aes_256_ctr(encrypted, key, nonce)
    assert decrypted == data
