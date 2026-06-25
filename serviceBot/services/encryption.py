import os
import base64
import hashlib

# AES S-Box
SBOX = [
    0x63, 0x7c, 0x77, 0x7b, 0xf2, 0x6b, 0x6f, 0xc5, 0x30, 0x01, 0x67, 0x2b, 0xfe, 0xd7, 0xab, 0x76,
    0xca, 0x82, 0xc9, 0x7d, 0xfa, 0x59, 0x47, 0xf0, 0xad, 0xd4, 0xa2, 0xaf, 0x9c, 0xa4, 0x72, 0xc0,
    0xb7, 0xfd, 0x93, 0x26, 0x36, 0x3f, 0xf7, 0xcc, 0x34, 0xa5, 0xe5, 0xf1, 0x71, 0xd8, 0x31, 0x15,
    0x04, 0xc7, 0x23, 0xc3, 0x18, 0x96, 0x05, 0x9a, 0x07, 0x12, 0x80, 0xe2, 0xeb, 0x27, 0xb2, 0x75,
    0x09, 0x83, 0x2c, 0x1a, 0x1b, 0x6e, 0x5a, 0xa0, 0x52, 0x3b, 0xd6, 0xb3, 0x29, 0xe3, 0x2f, 0x84,
    0x53, 0xd1, 0x00, 0xed, 0x20, 0xfc, 0xb1, 0x5b, 0x6a, 0xcb, 0xbe, 0x39, 0x4a, 0x4c, 0x58, 0xcf,
    0xd0, 0xef, 0xaa, 0xfb, 0x43, 0x4d, 0x33, 0x85, 0x45, 0xf9, 0x02, 0x7f, 0x50, 0x3c, 0x9f, 0xa8,
    0x51, 0xa3, 0x40, 0x8f, 0x92, 0x9d, 0x38, 0xf5, 0xbc, 0xb6, 0xda, 0x21, 0x10, 0xff, 0xf3, 0xd2,
    0xcd, 0x0c, 0x13, 0xec, 0x5f, 0x97, 0x44, 0x17, 0xc4, 0xa7, 0x7e, 0x3d, 0x64, 0x5d, 0x19, 0x73,
    0x60, 0x81, 0x4f, 0xdc, 0x22, 0x2a, 0x90, 0x88, 0x46, 0xee, 0xb8, 0x14, 0xde, 0x5e, 0x0b, 0xdb,
    0xe0, 0x32, 0x3a, 0x0a, 0x49, 0x06, 0x24, 0x5c, 0xc2, 0xd3, 0xac, 0x62, 0x91, 0x95, 0xe4, 0x79,
    0xe7, 0xc8, 0x37, 0x6d, 0x8d, 0xd5, 0x4e, 0xa9, 0x6c, 0x56, 0xf4, 0xea, 0x65, 0x7a, 0xae, 0x08,
    0xba, 0x78, 0x25, 0x2e, 0x1c, 0xa6, 0xb4, 0xc6, 0xe8, 0xdd, 0x74, 0x1f, 0x4b, 0xbd, 0x8b, 0x8a,
    0x70, 0x3e, 0xb5, 0x66, 0x48, 0x03, 0xf6, 0x0e, 0x61, 0x35, 0x57, 0xb9, 0x86, 0xc1, 0x1d, 0x9e,
    0xe1, 0xf8, 0x98, 0x11, 0x69, 0xd9, 0x8e, 0x94, 0x9b, 0x1e, 0x87, 0xe9, 0xce, 0x55, 0x28, 0xdf,
    0x8c, 0xa1, 0x89, 0x0d, 0xbf, 0xe6, 0x42, 0x68, 0x41, 0x99, 0x2d, 0x0f, 0xb0, 0x54, 0xbb, 0x16
]

RCON = [
    0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1B, 0x36
]

def sub_word(word):
    return [SBOX[b] for b in word]

def rot_word(word):
    return word[1:] + word[:1]

def key_expansion(key):
    # key should be 32 bytes (256 bits) -> 8 words
    words = []
    for i in range(8):
        words.append([key[4*i], key[4*i+1], key[4*i+2], key[4*i+3]])
    
    # 14 rounds for AES-256 -> 15 round keys -> 60 words
    while len(words) < 60:
        temp = words[-1]
        i = len(words)
        if i % 8 == 0:
            temp = sub_word(rot_word(temp))
            temp[0] ^= RCON[i // 8]
        elif i % 8 == 4:
            temp = sub_word(temp)
        
        # XOR with word 8 positions back
        w = [words[i-8][j] ^ temp[j] for j in range(4)]
        words.append(w)
        
    return [b for w in words for b in w]

def sub_bytes(state):
    for i in range(16):
        state[i] = SBOX[state[i]]

def shift_rows(state):
    # state: 16 bytes representing 4x4 column-major matrix
    # [s0, s1, s2, s3,
    #  s4, s5, s6, s7,
    #  s8, s9, s10,s11,
    #  s12,s13,s14,s15]
    # Row 0: s0, s4, s8, s12 (no shift)
    # Row 1: s1, s5, s9, s13 (shift left 1) -> s5, s9, s13, s1
    # Row 2: s2, s6, s10,s14 (shift left 2) -> s10,s14,s2, s6
    # Row 3: s3, s7, s11,s15 (shift left 3) -> s15,s3, s7, s11
    s = list(state)
    state[1], state[5], state[9], state[13] = s[5], s[9], s[13], s[1]
    state[2], state[6], state[10], state[14] = s[10], s[14], s[2], s[6]
    state[3], state[7], state[11], state[15] = s[15], s[3], s[7], s[11]

def xtime(a):
    return ((a << 1) ^ 0x1B) & 0xFF if (a & 0x80) else (a << 1) & 0xFF

def mix_single_column(r):
    # MixColumns on 4-byte column
    t = r[0] ^ r[1] ^ r[2] ^ r[3]
    u = r[0]
    r[0] ^= t ^ xtime(r[0] ^ r[1])
    r[1] ^= t ^ xtime(r[1] ^ r[2])
    r[2] ^= t ^ xtime(r[2] ^ r[3])
    r[3] ^= t ^ xtime(r[3] ^ u)

def mix_columns(state):
    for i in range(4):
        col = state[4*i : 4*i+4]
        mix_single_column(col)
        state[4*i : 4*i+4] = col

def add_round_key(state, round_key):
    for i in range(16):
        state[i] ^= round_key[i]

def aes_encrypt_block(block, expanded_key):
    # block is 16 bytes list
    state = list(block)
    add_round_key(state, expanded_key[0:16])
    for r in range(1, 14):
        sub_bytes(state)
        shift_rows(state)
        mix_columns(state)
        add_round_key(state, expanded_key[16*r : 16*r+16])
    sub_bytes(state)
    shift_rows(state)
    add_round_key(state, expanded_key[16*14 : 16*14+16])
    return bytes(state)

# We use CTR mode for simplicity and security (no padding, same encrypt/decrypt code)
def aes_256_ctr(data: bytes, key: bytes, nonce: bytes) -> bytes:
    # key must be 32 bytes, nonce must be 8 bytes
    expanded_key = key_expansion(key)
    out = bytearray()
    counter = 0
    for i in range(0, len(data), 16):
        # build 16-byte counter block: nonce (8 bytes) + counter (8 bytes, big endian)
        ctr_block = nonce + counter.to_bytes(8, 'big')
        keystream = aes_encrypt_block(ctr_block, expanded_key)
        chunk = data[i:i+16]
        for j in range(len(chunk)):
            out.append(chunk[j] ^ keystream[j])
        counter += 1
    return bytes(out)

# Deterministic key generation from system secret (fallback to standard key)
SECRET_KEY = hashlib.sha256(os.getenv("ENCRYPTION_KEY", "default-system-secret-key-32bytes-length").encode()).digest()

def encrypt_key(raw_key: str) -> str:
    if not raw_key:
        return ""
    # Generate random 8-byte nonce
    nonce = os.urandom(8)
    encrypted_bytes = aes_256_ctr(raw_key.encode('utf-8'), SECRET_KEY, nonce)
    # Pack as base64: nonce + encrypted_bytes
    return base64.b64encode(nonce + encrypted_bytes).decode('utf-8')

def decrypt_key(encrypted_str: str) -> str:
    if not encrypted_str:
        return ""
    data = base64.b64decode(encrypted_str.encode('utf-8'))
    nonce = data[:8]
    encrypted_bytes = data[8:]
    decrypted_bytes = aes_256_ctr(encrypted_bytes, SECRET_KEY, nonce)
    return decrypted_bytes.decode('utf-8')
